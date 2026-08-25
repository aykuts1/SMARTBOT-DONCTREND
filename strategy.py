from logger_setup import get_logger
import indicators

log = get_logger("strategy")


def on_1h_candle_close(symbol, candle, pool_1h, pool_4h, trade_manager, telegram, config):
    """Spec §5-6: Fisher(1H) kesisimi tetikleyici, EMA(21/50/100, 1H) ve
    MACD(4H, cache'lenmis) onaylari. Ucu de ayni yonde ise islem acilir.
    Cikis SADECE Fisher ters kesimiyle yapilir; ayni mum kapanisinda
    kapatma sonrasi yeni yonde kosullar tutuyorsa ayni mumda yeni islem
    acilir (flip, iki ayri adim olarak)."""
    ind = indicators.compute_1h_signals(pool_1h.get_candles(symbol), config)
    if not ind:
        return
    pool_1h.set_indicators(symbol, ind)

    if not (ind["fisher_cross_up"] or ind["fisher_cross_down"]):
        return

    trigger_dir = "long" if ind["fisher_cross_up"] else "short"
    ema_dir = ind["ema_direction"]
    macd_dir = pool_4h.get_indicators(symbol).get("macd_direction")

    existing = trade_manager.get_trade(symbol)
    if existing:
        if existing["side"] == trigger_dir:
            return  # zaten bu yonde pozisyon acik
        closed = trade_manager.close_trade(symbol, "fisher_ters_kesim", candle["close"])
        if not closed:
            return  # kapatma basarisiz, bu mumda yeni yon acilmaz

    entry_ok = (ema_dir == trigger_dir) and (macd_dir == trigger_dir)
    if not entry_ok:
        if telegram:
            telegram.send_signal_mismatch_skip(symbol, trigger_dir, ema_dir, macd_dir)
        return

    trade_manager.open_trade({"symbol": symbol, "side": trigger_dir, "entry_price": candle["close"]})


def on_4h_candle_close(symbol, pool_4h, config):
    """Spec §3.2: 4 saatlik MACD onay yonunu hesaplar ve cache'ler. Islem
    acmaz/kapatmaz. Cagirmadan once ilgili mum pool_4h'a eklenmis olmali."""
    prev_direction = pool_4h.get_indicators(symbol).get("macd_direction")
    result = indicators.compute_4h_macd(pool_4h.get_candles(symbol), config, prev_direction)
    pool_4h.set_indicators(symbol, result)
