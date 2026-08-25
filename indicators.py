import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Standart üstel hareketli ortalama (EMA)."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_fisher(high: pd.Series, low: pd.Series, period: int = 9):
    """
    Fisher Transform hesaplaması (John Ehlers formülü).

    Dönüş:
        fisher  -> mavi çizgi
        trigger -> sarı çizgi (fisher'ın 1 bar geciktirilmiş hali)
    """
    hl2 = (high + low) / 2

    max_h = hl2.rolling(window=period, min_periods=period).max()
    min_l = hl2.rolling(window=period, min_periods=period).min()
    rng = (max_h - min_l).replace(0, np.nan)

    raw = 0.66 * ((hl2 - min_l) / rng - 0.5)

    n = len(hl2)
    value = np.zeros(n)
    fisher = np.zeros(n)

    for i in range(1, n):
        r = raw.iloc[i]
        v = 0.0 if pd.isna(r) else (r + 0.67 * value[i - 1])
        v = max(min(v, 0.999), -0.999)
        value[i] = v
        fisher[i] = 0.5 * np.log((1 + v) / (1 - v)) + 0.5 * fisher[i - 1]

    fisher_series = pd.Series(fisher, index=hl2.index)
    trigger_series = fisher_series.shift(1)
    return fisher_series, trigger_series


def calculate_macd_line(close: pd.Series, fast_period: int, slow_period: int) -> pd.Series:
    """
    MACD çizgisi = hızlı EMA - yavaş EMA.
    Değer > 0 ise hızlı çizgi yavaş çizginin üstünde (long yönlü).
    Değer < 0 ise hızlı çizgi yavaş çizginin altında (short yönlü).
    """
    ema_fast = calculate_ema(close, fast_period)
    ema_slow = calculate_ema(close, slow_period)
    return ema_fast - ema_slow
