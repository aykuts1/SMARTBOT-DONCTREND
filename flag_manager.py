import threading
from logger_setup import get_logger

log = get_logger("flag_manager")


class FlagManager:
    """Spesifikasyon §3: Long/Short flag sistemi.

    Her sembol icin long ve short flag birbirinden bagimsiz iki ayri slot.
    Bir indikator (stokastik/macd) bir yonde kesisim verirse o yonde flag acilir.
    Flag'in bekledigi (acan indikatorden farkli) indikator ayni yonde kesisim
    verirse islem onaylanir. 5 mum icinde onaylanmazsa flag silinir. Flag'i acan
    indikator tekrar ayni yonde kesisim verirse sayac sifirlanir (bekleme uzar) -
    spesifikasyonda tanimlanmamis bir durum, guvenli varsayim olarak eklendi.
    """

    def __init__(self, expiry_candles=5):
        self.expiry = expiry_candles
        self._flags = {}  # symbol -> {"long": {"source","remaining"}|None, "short": ...}
        self._lock = threading.Lock()

    def process_candle_close(self, symbol, stoch_cross_up, stoch_cross_down,
                              macd_cross_up, macd_cross_down):
        with self._lock:
            state = self._flags.setdefault(symbol, {"long": None, "short": None})
            confirmed = []

            cross_by_direction = {
                "long": {"stoch": stoch_cross_up, "macd": macd_cross_up},
                "short": {"stoch": stoch_cross_down, "macd": macd_cross_down},
            }

            for direction, cross in cross_by_direction.items():
                flag = state[direction]

                if flag is not None:
                    waiting_for = "macd" if flag["source"] == "stoch" else "stoch"
                    if cross[waiting_for]:
                        confirmed.append(direction)
                        state[direction] = None
                        flag = None
                    elif cross[flag["source"]]:
                        flag["remaining"] = self.expiry
                    else:
                        flag["remaining"] -= 1
                        if flag["remaining"] <= 0:
                            log.debug("%s %s flag suresi doldu, silindi", symbol, direction)
                            state[direction] = None
                        flag = state[direction]

                if flag is None and direction not in confirmed:
                    if cross["stoch"] and cross["macd"]:
                        confirmed.append(direction)
                    elif cross["stoch"]:
                        state[direction] = {"source": "stoch", "remaining": self.expiry}
                        log.debug("%s %s flag acildi (kaynak=stoch)", symbol, direction)
                    elif cross["macd"]:
                        state[direction] = {"source": "macd", "remaining": self.expiry}
                        log.debug("%s %s flag acildi (kaynak=macd)", symbol, direction)

            if confirmed:
                log.info("%s onaylanan yonler: %s", symbol, confirmed)

            return confirmed

    def get_open_flags(self, symbol=None):
        with self._lock:
            if symbol:
                return dict(self._flags.get(symbol, {"long": None, "short": None}))
            return {s: dict(f) for s, f in self._flags.items()}

    def to_dict(self):
        with self._lock:
            return {s: dict(f) for s, f in self._flags.items()}

    def from_dict(self, data):
        with self._lock:
            self._flags = {s: dict(f) for s, f in (data or {}).items()}
