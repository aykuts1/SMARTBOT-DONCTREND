import time
import threading
import signal

from logger_setup import setup_logger, get_logger
from utils import load_config
from bybit_client import BybitClient
from data_pool import DataPool
from price_poller import PricePoller
from trade_manager import TradeManager
from telegram_bot import TelegramBot
import strategy

setup_logger()
log = get_logger("main")


class BotManager:
    def __init__(self):
        self.config = load_config()
        self.running = False
        self._stop_reason = "Manuel durdurma"

        self.bybit = BybitClient()
        self.pool_1h = DataPool()
        self.pool_4h = DataPool()
        self.telegram = TelegramBot(bot_manager=self)
        self.trade_manager = TradeManager(self.bybit, self.config, self.telegram)

        self._stop_event = threading.Event()
        self.poller = None

    # === BASLATMA ===

    def run(self):
        log.info("=" * 60)
        log.info("TRADE BOT BASLATILIYOR")
        log.info("=" * 60)

        if not self.bybit.test_connection():
            log.critical("Bybit baglantisi kurulamadi!")
            return

        coins = self.config["global"]["coin_listesi"]
        self.bybit.load_instrument_info(coins)
        self.bybit.setup_account(coins, self.config["global"]["kaldirac"])

        balance_info = self.bybit.get_balance()
        if not balance_info:
            log.critical("Bakiye alinamadi!")
            return
        log.info("Bakiye: %.2f USDT", balance_info["total"])

        # Spec §8: bot her restart'ta tamamen sifirdan baslar, acik islemler
        # ve borsadaki pozisyonlarla senkronize olmaz.
        self._log_ignored_positions()
        self._load_initial_data(coins)

        self.poller = PricePoller(self.bybit)
        self.poller.add_timeframe(self.config["global"]["timeframe_4h"], self._on_4h_candle_close, prefetch_delay_sn=3)
        self.poller.add_timeframe(self.config["global"]["timeframe_1h"], self._on_1h_candle_close, prefetch_delay_sn=6)
        self.poller.start(coins)

        self.running = True
        self.telegram.start_polling()
        self.telegram.send_bot_started(balance_info["total"], self.config["global"]["marjin_orani"],
                                        self.config["global"]["kaldirac"], len(coins))

        self._start_background_threads()

        log.info("Bot calisiyor, Ctrl+C ile durdurulabilir")
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(1)
        except KeyboardInterrupt:
            self._stop_reason = "Klavye ile durdurma"
        finally:
            self._shutdown(self._stop_reason)

    def _log_ignored_positions(self):
        positions = self.bybit.get_positions()
        if positions:
            log.info("Borsada %d acik pozisyon var, spec §8 geregi bot bunlari yonetmeyecek", len(positions))
        else:
            log.info("Acik pozisyon bulunmuyor")

    def _load_initial_data(self, coins):
        cfg = self.config["global"]
        log.info("Baslangic verileri yukleniyor (%d coin, 1H=%d mum, 4H=%d mum)...",
                  len(coins), cfg["baslangic_mum_sayisi_1h"], cfg["baslangic_mum_sayisi_4h"])
        for symbol in coins:
            candles_1h = self.bybit.get_klines(symbol, cfg["timeframe_1h"], cfg["baslangic_mum_sayisi_1h"])
            if candles_1h:
                self.pool_1h.set_initial_candles(symbol, candles_1h)
            time.sleep(0.1)

            candles_4h = self.bybit.get_klines(symbol, cfg["timeframe_4h"], cfg["baslangic_mum_sayisi_4h"])
            if candles_4h:
                self.pool_4h.set_initial_candles(symbol, candles_4h)
                strategy.on_4h_candle_close(symbol, self.pool_4h, self.config)
            time.sleep(0.1)

    # === GERI CAGRILAR (mum kapanisi) ===

    def _on_1h_candle_close(self, symbol, candle):
        self.pool_1h.add_candle(symbol, candle)
        if not self.running:
            return
        try:
            strategy.on_1h_candle_close(symbol, candle, self.pool_1h, self.pool_4h, self.trade_manager, self.telegram, self.config)
        except Exception as e:
            log.error("%s 1H mum kapanis isleme hatasi: %s", symbol, e)

    def _on_4h_candle_close(self, symbol, candle):
        self.pool_4h.add_candle(symbol, candle)
        if not self.running:
            return
        try:
            strategy.on_4h_candle_close(symbol, self.pool_4h, self.config)
        except Exception as e:
            log.error("%s 4H mum kapanis isleme hatasi: %s", symbol, e)

    # === ARKA PLAN DONGULERI ===

    def _start_background_threads(self):
        threading.Thread(target=self._exchange_poll_loop, daemon=True, name="exchange_poll_loop").start()
        threading.Thread(target=self._report_loop, daemon=True, name="report_loop").start()

    def _exchange_poll_loop(self):
        """Spec §7: borsadaki sabit %4 SL kendiliginden tetiklendiginde
        bunu algilamak icin her 5sn takip edilen pozisyonlar kontrol edilir."""
        while not self._stop_event.is_set():
            self._stop_event.wait(5)
            if self._stop_event.is_set() or not self.running:
                continue
            try:
                self.trade_manager.poll_exchange_closures()
            except Exception as e:
                log.error("Borsa kapanis kontrolu hatasi: %s", e)

    def _report_loop(self):
        """Spec §9.5: her 1, 6 ve 24 saatte bir periyodik rapor."""
        last_1h = last_6h = last_24h = time.time()
        cfg_tg = self.config.get("telegram", {})

        while not self._stop_event.is_set():
            self._stop_event.wait(60)
            if self._stop_event.is_set():
                break
            now = time.time()
            if now - last_1h >= 3600 and cfg_tg.get("rapor_1s", True):
                self.telegram.send_1h_report()
                last_1h = now
            if now - last_6h >= 21600 and cfg_tg.get("rapor_6s", True):
                self.telegram.send_6h_report()
                last_6h = now
            if now - last_24h >= 86400 and cfg_tg.get("rapor_24s", True):
                self.telegram.send_24h_report()
                last_24h = now

    # === KAPATMA ===

    def _shutdown(self, reason):
        self.running = False
        self._stop_event.set()
        if self.poller:
            self.poller.stop()
        self.telegram.send_bot_stopped(reason, self.trade_manager.get_total_count())
        log.info("Bot durduruldu: %s", reason)


def _install_signal_handlers(manager):
    def handler(signum, frame):
        try:
            name = signal.Signals(signum).name
        except Exception:
            name = str(signum)
        log.info("Sinyal alindi (%s), bot durduruluyor...", name)
        manager._stop_reason = f"Sinyal alindi: {name}"
        manager._stop_event.set()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


if __name__ == "__main__":
    manager = BotManager()
    _install_signal_handlers(manager)
    manager.run()
