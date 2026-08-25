import pandas as pd

import config
import indicators


def analyze_symbol(df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> dict:
    """
    Bir coin için 1H ve 4H verisini analiz eder, indikatör istasyonu.
    Son kapanan mumdaki durumları ve varsa yeni Fisher tetiğini döndürür.
    """
    high_1h = df_1h["high"]
    low_1h = df_1h["low"]
    close_1h = df_1h["close"]

    fisher, trigger = indicators.calculate_fisher(high_1h, low_1h, config.FISHER_PERIOD)

    ema21 = indicators.calculate_ema(close_1h, config.EMA_FAST)
    ema50 = indicators.calculate_ema(close_1h, config.EMA_MID)
    ema100 = indicators.calculate_ema(close_1h, config.EMA_SLOW)

    close_4h = df_4h["close"]
    macd_line = indicators.calculate_macd_line(close_4h, config.MACD_FAST, config.MACD_SLOW)

    last, prev = -1, -2

    fisher_cross_up = bool(fisher.iloc[prev] <= trigger.iloc[prev] and fisher.iloc[last] > trigger.iloc[last])
    fisher_cross_down = bool(fisher.iloc[prev] >= trigger.iloc[prev] and fisher.iloc[last] < trigger.iloc[last])

    ema_long = bool(ema21.iloc[last] > ema50.iloc[last] > ema100.iloc[last])
    ema_short = bool(ema21.iloc[last] < ema50.iloc[last] < ema100.iloc[last])

    macd_long = bool(macd_line.iloc[last] > 0)
    macd_short = bool(macd_line.iloc[last] < 0)

    return {
        "fisher_cross_up": fisher_cross_up,
        "fisher_cross_down": fisher_cross_down,
        "ema_long": ema_long,
        "ema_short": ema_short,
        "macd_long": macd_long,
        "macd_short": macd_short,
        "close_price": float(close_1h.iloc[last]),
    }


def decide(signals: dict, has_position: bool, position_side: str = None):
    """
    Dönüş:
        ("exit", None)
        ("enter", "long" | "short")
        ("skip", "atlama sebebi")
        ("none", None)
    """
    # --- Pozisyon açıksa: sadece çıkış kontrolü yapılır (Fisher'a bağlı) ---
    if has_position:
        if position_side == "long" and signals["fisher_cross_down"]:
            return "exit", None
        if position_side == "short" and signals["fisher_cross_up"]:
            return "exit", None
        return "none", None

    # --- Pozisyon yoksa: giriş kontrolü ---
    if signals["fisher_cross_up"]:
        if signals["ema_long"] and signals["macd_long"]:
            return "enter", "long"
        eksikler = []
        if not signals["ema_long"]:
            eksikler.append("EMA onayı yok")
        if not signals["macd_long"]:
            eksikler.append("MACD onayı yok")
        return "skip", " ve ".join(eksikler)

    if signals["fisher_cross_down"]:
        if signals["ema_short"] and signals["macd_short"]:
            return "enter", "short"
        eksikler = []
        if not signals["ema_short"]:
            eksikler.append("EMA onayı yok")
        if not signals["macd_short"]:
            eksikler.append("MACD onayı yok")
        return "skip", " ve ".join(eksikler)

    return "none", None
