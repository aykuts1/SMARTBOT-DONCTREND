import numpy as np

FISHER_CLAMP = 0.999


def calc_ema(closes, period):
    if len(closes) < period:
        return []
    ema = [0.0] * len(closes)
    multiplier = 2.0 / (period + 1)
    ema[period - 1] = float(np.mean(closes[:period]))
    for i in range(period, len(closes)):
        ema[i] = (closes[i] - ema[i - 1]) * multiplier + ema[i - 1]
    return ema


def calc_fisher(highs, lows, period):
    """Ehlers Fisher Transform. Kaynak = (high+low)/2, `period` periyotluk
    rolling min/max ile -1..1 araligina normalize edilir. Doner:
    (fisher, trigger) - trigger, fisher'in bir onceki degeridir."""
    n = len(highs)
    if n < period:
        return [], []

    src = [(highs[i] + lows[i]) / 2.0 for i in range(n)]
    value = [0.0] * n
    fisher = [0.0] * n

    for i in range(period - 1, n):
        window = src[i - period + 1:i + 1]
        hi, lo = max(window), min(window)
        rng = hi - lo
        raw = 0.0 if rng == 0 else 2 * ((src[i] - lo) / rng - 0.5)
        prev_value = value[i - 1] if i > 0 else 0.0
        v = max(-FISHER_CLAMP, min(FISHER_CLAMP, 0.33 * raw + 0.67 * prev_value))
        value[i] = v
        prev_fisher = fisher[i - 1] if i > 0 else 0.0
        fisher[i] = 0.5 * np.log((1 + v) / (1 - v)) + 0.5 * prev_fisher

    trigger = [0.0] + fisher[:-1]
    return fisher, trigger


def detect_crossover_up(fast, slow, index):
    if index < 1:
        return False
    return fast[index - 1] <= slow[index - 1] and fast[index] > slow[index]


def detect_crossover_down(fast, slow, index):
    if index < 1:
        return False
    return fast[index - 1] >= slow[index - 1] and fast[index] < slow[index]


def calc_ema_direction(closes, p_kisa, p_orta, p_uzun):
    """Spec §3.1: EMA(kisa/orta/uzun) NET siralamasindan trend yonu.
    kisa>orta>uzun -> long, uzun>orta>kisa -> short, aksi halde None."""
    ema_kisa = calc_ema(closes, p_kisa)
    ema_orta = calc_ema(closes, p_orta)
    ema_uzun = calc_ema(closes, p_uzun)
    if not ema_kisa or not ema_orta or not ema_uzun:
        return None

    k, o, u = ema_kisa[-1], ema_orta[-1], ema_uzun[-1]
    if k > o > u:
        return "long"
    if u > o > k:
        return "short"
    return None


def calc_macd_direction(closes, p_hizli, p_yavas, prev_direction=None):
    """Spec §3.2: MACD = hizli EMA(9) ile yavas EMA(21) dogrudan
    karsilastirmasi (sinyal cizgisi yok). Esitlikte onceki yon korunur."""
    ema_hizli = calc_ema(closes, p_hizli)
    ema_yavas = calc_ema(closes, p_yavas)
    if not ema_hizli or not ema_yavas:
        return prev_direction

    hizli, yavas = ema_hizli[-1], ema_yavas[-1]
    if hizli > yavas:
        return "long"
    if hizli < yavas:
        return "short"
    return prev_direction


def compute_1h_signals(candles, config):
    """Spec §3.1/§3.3: Fisher Transform kesisimi (giris tetikleyici + cikis
    sinyali) ve EMA(21/50/100) trend siralamasini hesaplar. 1H MACD de
    spec §3.2 geregi ayrica olculur (karar akisinda kullanilmaz, bilgi
    amaclidir)."""
    cfg = config.get("indicators", {})
    fisher_period = cfg.get("fisher_uzunluk", 9)
    ema_kisa, ema_orta, ema_uzun = cfg.get("ema_kisa", 21), cfg.get("ema_orta", 50), cfg.get("ema_uzun", 100)
    macd_hizli, macd_yavas = cfg.get("macd_hizli", 9), cfg.get("macd_yavas", 21)

    if not candles or len(candles) < ema_uzun:
        return {}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    fisher, trigger = calc_fisher(highs, lows, fisher_period)
    if not fisher:
        return {}

    idx = len(closes) - 1
    return {
        "fisher_cross_up": detect_crossover_up(fisher, trigger, idx),
        "fisher_cross_down": detect_crossover_down(fisher, trigger, idx),
        "ema_direction": calc_ema_direction(closes, ema_kisa, ema_orta, ema_uzun),
        "macd_1h_direction": calc_macd_direction(closes, macd_hizli, macd_yavas),
    }


def compute_4h_macd(candles, config, prev_direction=None):
    """Spec §3.2: 4 saatlik MACD - islem acilis/kapanisinda tek onay
    kaynagi olarak kullanilan yon. Sadece pool_4h uzerindeki cache'i
    guncellemek icin cagrilir, islem acmaz/kapatmaz."""
    cfg = config.get("indicators", {})
    macd_hizli, macd_yavas = cfg.get("macd_hizli", 9), cfg.get("macd_yavas", 21)

    if not candles or len(candles) < macd_yavas:
        return {"macd_direction": prev_direction}

    closes = [c["close"] for c in candles]
    direction = calc_macd_direction(closes, macd_hizli, macd_yavas, prev_direction)
    return {"macd_direction": direction}
