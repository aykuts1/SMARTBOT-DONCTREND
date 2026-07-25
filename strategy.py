from logger_setup import get_logger
from indicators import compute_signals

log = get_logger("strategy")


def on_candle_close(symbol, candle, data_pool, flag_manager, config):
    """Spesifikasyon §2-5: kesisim tespiti -> flag onayi -> lose/win exit hesaplama.
    Onaylanan yonler icin acilacak islem isteklerini dondurur."""
    candles = data_pool.get_candles(symbol)
    signals = compute_signals(candles, config)
    if not signals:
        return []

    data_pool.set_indicators(symbol, signals)

    directions = flag_manager.process_candle_close(
        symbol,
        signals["stoch_cross_up"], signals["stoch_cross_down"],
        signals["macd_cross_up"], signals["macd_cross_down"]
    )
    if not directions:
        return []

    cfg = config.get("global", {})
    rr_ratio = cfg.get("rr_orani", 2.5)
    max_atr_mult = cfg.get("max_atr_carpani", 4)

    entry_price = candle["close"]
    atr = signals["atr"][-1]
    bb_upper = signals["bb_upper"][-1]
    bb_lower = signals["bb_lower"][-1]
    max_dist = max_atr_mult * atr

    requests = []
    for direction in directions:
        if direction == "long":
            lose_exit = bb_lower
            if entry_price - lose_exit > max_dist:
                lose_exit = entry_price - max_dist
            dist = entry_price - lose_exit
            win_exit = entry_price + rr_ratio * dist
        else:
            lose_exit = bb_upper
            if lose_exit - entry_price > max_dist:
                lose_exit = entry_price + max_dist
            dist = lose_exit - entry_price
            win_exit = entry_price - rr_ratio * dist

        if dist <= 0:
            log.warning("%s %s: gecersiz mesafe (dist=%.6f), sinyal atlaniyor", symbol, direction, dist)
            continue

        requests.append({
            "symbol": symbol,
            "side": direction,
            "entry_price": entry_price,
            "lose_exit": lose_exit,
            "win_exit": win_exit,
        })

    return requests
