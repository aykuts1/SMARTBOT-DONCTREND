import threading
from logger_setup import get_logger

log = get_logger("data_pool")

_MAX_CANDLES = 300
_TRIM_TO = 250


class DataPool:
    """Bir zaman dilimi (1H veya 4H) icin coin basina mum gecmisi ve son
    hesaplanan gosterge sonuclarinin thread-safe deposu."""

    def __init__(self):
        self._lock = threading.Lock()
        self._candles = {}
        self._indicators = {}

    def set_initial_candles(self, symbol, candles):
        with self._lock:
            self._candles[symbol] = list(candles)
            log.debug("%s: %d mum yuklendi", symbol, len(candles))

    def add_candle(self, symbol, candle):
        with self._lock:
            candles = self._candles.setdefault(symbol, [])
            candles.append(candle)
            if len(candles) > _MAX_CANDLES:
                self._candles[symbol] = candles[-_TRIM_TO:]

    def get_candles(self, symbol):
        with self._lock:
            return list(self._candles.get(symbol, []))

    def set_indicators(self, symbol, indicators):
        with self._lock:
            self._indicators[symbol] = indicators

    def get_indicators(self, symbol):
        with self._lock:
            return dict(self._indicators.get(symbol, {}))
