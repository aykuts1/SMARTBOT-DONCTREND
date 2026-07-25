import threading
from logger_setup import get_logger

log = get_logger("data_pool")


class DataPool:
    def __init__(self):
        self._lock = threading.Lock()
        self._candles = {}
        self._prices = {}
        self._indicators = {}

    def set_initial_candles(self, symbol, candles):
        with self._lock:
            self._candles[symbol] = list(candles)
            if candles:
                self._prices[symbol] = candles[-1]["close"]
            log.debug("%s: %d mum yuklendi", symbol, len(candles))

    def add_candle(self, symbol, candle):
        with self._lock:
            if symbol not in self._candles:
                self._candles[symbol] = []
            self._candles[symbol].append(candle)
            self._prices[symbol] = candle["close"]

            if len(self._candles[symbol]) > 300:
                self._candles[symbol] = self._candles[symbol][-250:]

    def update_price(self, symbol, price):
        with self._lock:
            self._prices[symbol] = price

    def get_candles(self, symbol, count=None):
        with self._lock:
            candles = self._candles.get(symbol, [])
            if count:
                return list(candles[-count:])
            return list(candles)

    def get_price(self, symbol):
        with self._lock:
            return self._prices.get(symbol, 0)

    def get_all_prices(self):
        with self._lock:
            return dict(self._prices)

    def set_indicators(self, symbol, indicators):
        with self._lock:
            self._indicators[symbol] = indicators

    def get_indicators(self, symbol):
        with self._lock:
            return self._indicators.get(symbol, {})

    def get_last_candle(self, symbol):
        with self._lock:
            candles = self._candles.get(symbol, [])
            if candles:
                return dict(candles[-1])
            return None

    def get_prev_candle(self, symbol, offset=1):
        with self._lock:
            candles = self._candles.get(symbol, [])
            if len(candles) > offset:
                return dict(candles[-(offset + 1)])
            return None

    def has_data(self, symbol):
        with self._lock:
            return symbol in self._candles and len(self._candles[symbol]) > 0
