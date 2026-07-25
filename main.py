import time
import threading
import signal

from logger_setup import setup_logger, get_logger
from utils import load_config, is_our_order
from bybit_client import BybitClient
from data_pool import DataPool
from price_poller import PricePoller
from trade_manager import TradeManager
from telegram_bot import TelegramBot
from flag_manager import FlagManager
import strategy
import state_store

setup_logger()
log = get_logger("main")


class BotManager:
    def __init__(self):
        self.config = load_config()
        self.running = False
        self.start_time = 0
        self._stop_reason = "Manuel durdurma"

        self.bybit = BybitClient()
        self.data_pool = DataPool()
        self.flag_manager = FlagManager(self.config["global"].get("flag_gecerlilik_mum", 5))
        self.telegram = TelegramBot(bot_manager=self)
        self.trade_manager = TradeManager(
            self.bybit, self.config, self.telegram, on_state_change=self._persist_state
        )

        self._stop_event = threading.Event()
        self._scan_thread = None
        self._report_thread = None
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

        leverage = self.config["global"]["kaldirac"]
        self.bybit.setup_account(coins, leverage)

        balance_info = self.bybit.get_balance()
        if not balance_info:
            log.critical("Bakiye alinamadi!")
            return
        log.info("Bakiye: %.2f USDT", balance_info["total"])

        self._load_state()
        self._load_initial_data(coins)
        self._check_existing_positions()

        interval = self.config["global"]["timeframe"]
        self.poller = PricePoller(self.bybit, self.data_pool, self._on_candle_close)
        self.poller.start(coins, interval)

        self.running = True
        self.start_time = time.time()

        self.telegram.start_polling()

        open_count = self.trade_manager.get_total_count()
        margin_pct = self.config["global"]["marjin_orani"]
        self.telegram.send_bot_started(balance_info["total"], margin_pct, leverage, len(coins), open_count)

        self._start_background_threads()

        log.info("Bot calisiyor, Ctrl+C ile durdurulabilir")
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(1)
        except KeyboardInterrupt:
            self._stop_reason = "Klavye ile durdurma"
        finally:
            self._shutdown(self._stop_reason)

    def _load_state(self):
        data = state_store.load()
        if not data:
            return
        self.trade_manager.from_dict(data.get("trade_manager", {}))
        self.flag_manager.from_dict(data.get("flags", {}))
        self.telegram.from_dict(data.get("telegram_stats", {}))
        log.info("Onceki state geri yuklendi (%d sanal islem)", self.trade_manager.get_total_count())

    def _persist_state(self):
        state_store.save({
            "trade_manager": self.trade_manager.to_dict(),
            "flags": self.flag_manager.to_dict(),
            "telegram_stats": self.telegram.to_dict(),
        })

    def _load_initial_data(self, coins):
        limit = self.config["global"]["baslangic_mum_sayisi"]
        interval = self.config["global"]["timeframe"]
        log.info("Baslangic verileri yukleniyor (%d coin, %d mum)...", len(coins), limit)
        for symbol in coins:
            candles = self.bybit.get_klines(symbol, interval, limit)
            if candles:
                self.data_pool.set_initial_candles(symbol, candles)
            time.sleep(0.1)

    def _check_existing_positions(self):
        positions = self.bybit.get_positions()
        if not positions:
            log.info("Acik pozisyon bulunmuyor")
            return
        our_count = sum(1 for p in positions if is_our_order(p.get("order_link_id", "")))
        untagged = [p for p in positions if not is_our_order(p.get("order_link_id", ""))]
        log.info("Pozisyon ozeti: %d bizim, %d etiketsiz", our_count, len(untagged))
        self.trade_manager.reconcile()

    # === GERI CAGRILAR ===

    def _on_candle_close(self, symbol, candle):
        self.data_pool.add_candle(symbol, candle)
        if not self.running:
            return
        try:
            requests = strategy.on_candle_close(symbol, candle, self.data_pool, self.flag_manager, self.config)
            self._persist_state()
            for req in requests:
                self.trade_manager.open_trade(req)
        except Exception as e:
            log.error("%s mum kapanis isleme hatasi: %s", symbol, e)

    # === ARKA PLAN DONGULERI ===

    def _start_background_threads(self):
        self._scan_thread = threading.Thread(target=self._scan_loop, daemon=True, name="scan_loop")
        self._scan_thread.start()
        self._report_thread = threading.Thread(target=self._report_loop, daemon=True, name="report_loop")
        self._report_thread.start()

    def _scan_loop(self):
        coins = self.config["global"]["coin_listesi"]
        reconcile_counter = 0
        while not self._stop_event.is_set():
            self._stop_event.wait(5)
            if self._stop_event.is_set() or not self.running:
                continue

            for symbol in coins:
                price = self.data_pool.get_price(symbol)
                if price and price > 0:
                    try:
                        self.trade_manager.check_exit(symbol, price)
                    except Exception as e:
                        log.error("%s check_exit hatasi: %s", symbol, e)

            reconcile_counter += 1
            if reconcile_counter >= 60:
                reconcile_counter = 0
                try:
                    self.trade_manager.reconcile()
                except Exception as e:
                    log.error("Reconcile hatasi: %s", e)

    def _report_loop(self):
        last_1h = time.time()
        last_6h = time.time()
        last_24h = time.time()
        cfg_tg = self.config.get("telegram", {})

        while not self._stop_event.is_set():
            self._stop_event.wait(60)
            if self._stop_event.is_set():
                break

            now = time.time()
            balance_info = self.bybit.get_balance()
            balance = balance_info["total"] if balance_info else 0
            open_count = self.trade_manager.get_total_count()

            if now - last_1h >= 3600 and cfg_tg.get("rapor_1s", True):
                self.telegram.send_hourly_report(balance, open_count)
                self._persist_state()
                last_1h = now

            if now - last_6h >= 21600 and cfg_tg.get("rapor_6s", True):
                self.telegram.send_6h_report(balance)
                self._persist_state()
                last_6h = now

            if now - last_24h >= 86400 and cfg_tg.get("rapor_24s", True):
                self.telegram.send_24h_report(balance)
                self._persist_state()
                last_24h = now

    # === KAPATMA ===

    def _shutdown(self, reason):
        self.running = False
        self._stop_event.set()
        if self.poller:
            self.poller.stop()
        open_count = self.trade_manager.get_total_count()
        self.telegram.send_bot_stopped(reason, open_count)
        self._persist_state()
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
