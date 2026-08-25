import time
import threading
from logger_setup import get_logger

log = get_logger("price_poller")


class PricePoller:
    """Spec §4: 1H ve 4H mum verileri HER MUM KAPANISINDA cekilir; tum
    kararlar kapanmis mumlar uzerinden alinir. Canli fiyat takibi yapilmaz -
    giris/cikis fiyatlari da kapanan mumun close'udur."""

    def __init__(self, bybit_client):
        self.bybit = bybit_client
        self._stop_event = threading.Event()
        self._symbols = []
        self._watchers = []

    def add_timeframe(self, interval, on_close, prefetch_delay_sn=5):
        self._watchers.append({
            "interval": interval,
            "interval_sec": int(interval) * 60,
            "on_close": on_close,
            "prefetch_delay_sn": prefetch_delay_sn,
            "last_boundary": None,
        })

    def start(self, symbols):
        self._symbols = symbols
        now = time.time()
        for w in self._watchers:
            w["last_boundary"] = int(now // w["interval_sec"]) * w["interval_sec"]
        threading.Thread(target=self._loop, daemon=True, name="price_poller").start()
        log.info("PricePoller baslatildi (%d coin, %d zaman dilimi)", len(symbols), len(self._watchers))

    def stop(self):
        self._stop_event.set()

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                for w in self._watchers:
                    self._check_watcher(w)
            except Exception as e:
                log.error("Poller dongu hatasi: %s", e)
            self._stop_event.wait(5)

    def _check_watcher(self, w):
        current = int(time.time() // w["interval_sec"]) * w["interval_sec"]
        if current <= w["last_boundary"]:
            return
        w["last_boundary"] = current
        log.info("Mum kapanisi algilandi (%s dk), %d sn bekleniyor...", w["interval"], w["prefetch_delay_sn"])
        threading.Thread(
            target=self._fetch_and_trigger, args=(w,), daemon=True, name="candle_close_%s" % w["interval"]
        ).start()

    def _fetch_and_trigger(self, w):
        time.sleep(w["prefetch_delay_sn"])
        log.info("Kapanan mum verileri cekiliyor (%s dk, %d coin)...", w["interval"], len(self._symbols))
        for symbol in self._symbols:
            if self._stop_event.is_set():
                break
            try:
                candles = self.bybit.get_klines(symbol, w["interval"], limit=3)
                if len(candles) >= 2:
                    closed_candle = candles[-2]
                    w["on_close"](symbol, closed_candle)
                time.sleep(0.15)
            except Exception as e:
                log.error("%s (%s dk) kapanan mum hatasi: %s", symbol, w["interval"], e)
