import time
import threading
from logger_setup import get_logger

log = get_logger("price_poller")


class PricePoller:
    """Spec §10: her 5 saniyede fiyat cekilir; 15dk mum kapanisinda
    kapanan mum verisi 5sn gecikmeyle cekilip on_candle_close tetiklenir."""

    def __init__(self, bybit_client, data_pool, on_candle_close):
        self.bybit = bybit_client
        self.data_pool = data_pool
        self._on_candle_close = on_candle_close
        self._stop_event = threading.Event()
        self._symbols = []
        self._interval = "15"
        self._last_boundary = None
        self._last_price_time = 0

    def start(self, symbols, interval):
        self._symbols = symbols
        self._interval = interval
        self._last_boundary = self._current_boundary()
        thread = threading.Thread(target=self._loop, daemon=True, name="price_poller")
        thread.start()
        log.info("PricePoller baslatildi (%d coin, %s dk)", len(symbols), interval)

    def stop(self):
        self._stop_event.set()

    @property
    def seconds_since_last_price(self):
        if self._last_price_time == 0:
            return -1
        return time.time() - self._last_price_time

    def _current_boundary(self):
        interval_sec = int(self._interval) * 60
        return int(time.time() // interval_sec) * interval_sec

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._update_prices()
                self._check_candle_close()
            except Exception as e:
                log.error("Poller dongu hatasi: %s", e)
            self._stop_event.wait(5)

    def _update_prices(self):
        try:
            result = self.bybit.client.get_tickers(category="linear")
            if result["retCode"] == 0:
                symbol_set = set(self._symbols)
                for item in result["result"]["list"]:
                    if item["symbol"] in symbol_set:
                        price = float(item["lastPrice"])
                        if price > 0:
                            self.data_pool.update_price(item["symbol"], price)
                self._last_price_time = time.time()
            else:
                log.warning("Fiyat alinamadi: %s", result.get("retMsg", ""))
        except Exception as e:
            log.error("Fiyat guncelleme hatasi: %s", e)

    def _check_candle_close(self):
        current = self._current_boundary()
        if current <= self._last_boundary:
            return
        self._last_boundary = current
        log.info("Mum kapanisi algilandi, 5 sn bekleniyor...")
        threading.Thread(
            target=self._fetch_and_trigger, daemon=True, name="candle_close"
        ).start()

    def _fetch_and_trigger(self):
        time.sleep(5)
        log.info("Kapanan mum verileri cekiliyor (%d coin)...", len(self._symbols))
        for symbol in self._symbols:
            if self._stop_event.is_set():
                break
            try:
                candles = self.bybit.get_klines(symbol, self._interval, limit=3)
                if len(candles) >= 2:
                    closed_candle = candles[-2]
                    self._on_candle_close(symbol, closed_candle)
                    log.debug("%s kapanan mum: C=%.4f", symbol, closed_candle["close"])
                time.sleep(0.15)
            except Exception as e:
                log.error("%s kapanan mum hatasi: %s", symbol, e)
