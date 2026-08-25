import time

import config
import notifier
import risk_manager
import strategy
import utils
from bybit_client import BybitClient
from state import BotState


# ---------- Zamanlama ----------

def wait_for_next_hour_close(client: BybitClient):
    """
    1 saatlik mum kapanışından ~10 saniye sonrasına kadar bekler.
    Bekleme tek seferde değil, KEEPALIVE_INTERVAL_SEC'lik parçalar halinde yapılır;
    her parçadan sonra Bybit'e küçük bir istek (get_server_time) atılır. Bu istek
    Railway'in "Serverless / App Sleeping" özelliğinin servisi uykuya almasını engeller
    (Railway, 10 dakika boyunca dışarıya hiç istek gitmezse servisi uykuya alıyor).
    """
    now_ts = time.time()
    next_ts = (int(now_ts // 3600) + 1) * 3600 + 10

    while True:
        now_ts = time.time()
        remaining = next_ts - now_ts
        if remaining <= 0:
            return
        chunk = min(remaining, config.KEEPALIVE_INTERVAL_SEC)
        time.sleep(chunk)
        try:
            client.session.get_server_time()
        except Exception as e:
            print(f"[BİLGİ] Keepalive isteği başarısız: {e}")


# ---------- Pozisyon senkronizasyonu ----------

def reconcile_positions(client: BybitClient, state: BotState):
    """
    Botun hafızasındaki açık pozisyonları borsadaki gerçek durumla karşılaştırır.
    SL ile (ya da başka bir sebeple) borsa tarafında kapanmış pozisyonları tespit edip
    hafızadan siler ve bildirim gönderir. Bu kontrol olmadan slotlar yanlış dolu görünür.
    """
    for symbol in list(state.open_positions.keys()):
        try:
            size = client.get_open_position_size(symbol)
        except Exception as e:
            print(f"[HATA] {symbol} pozisyon kontrolü başarısız: {e}")
            continue

        if size <= 0:
            pos = state.open_positions[symbol]
            notifier.send_message(
                f"🛑 <b>{symbol}</b>\n"
                f"Pozisyon borsa tarafında kapanmış (muhtemelen SL).\n"
                f"Yön: {pos['side'].upper()} | Giriş: {pos['entry_price']}"
            )
            state.remove_position(symbol)


# ---------- Giriş / Çıkış işlemleri ----------

def execute_entry(client: BybitClient, state: BotState, symbol: str, side: str, price: float):
    if not risk_manager.has_free_slot(state):
        notifier.send_message(
            f"🚫 <b>{symbol}</b>\nİşlem atlandı: Tüm slotlar dolu "
            f"({state.open_position_count()}/{config.MAX_OPEN_POSITIONS})."
        )
        return

    try:
        balance = client.get_available_balance()
    except Exception as e:
        print(f"[HATA] {symbol} bakiye alınamadı: {e}")
        return

    try:
        info = client.get_instrument_info(symbol)
    except Exception as e:
        print(f"[HATA] {symbol} enstrüman bilgisi alınamadı: {e}")
        return

    sized = risk_manager.calc_position_size(balance, price, info["qty_step"], info["min_qty"])
    if sized is None:
        notifier.send_message(f"🚫 <b>{symbol}</b>\nİşlem atlandı: Bakiye yetersiz.")
        return

    qty, margin, notional = sized
    qty_str = utils.format_qty(qty, info["qty_step"])

    order_side = "Buy" if side == "long" else "Sell"
    sl_price = price * (1 - config.STOP_LOSS_PCT) if side == "long" else price * (1 + config.STOP_LOSS_PCT)
    sl_str = utils.round_to_tick(sl_price, info["tick_size"])

    try:
        client.ensure_leverage(symbol)
        client.place_market_order(symbol, order_side, qty_str, stop_loss=sl_str)
    except Exception as e:
        notifier.send_message(f"❌ <b>{symbol}</b>\nİşlem açma HATASI: {e}")
        return

    state.add_position(symbol, side, price, qty_str, sl_str)

    notifier.send_message(
        f"✅ <b>{symbol}</b> {side.upper()} işlem açıldı\n"
        f"Giriş: {price}\n"
        f"Miktar: {qty_str}\n"
        f"SL: {sl_str} (%{int(config.STOP_LOSS_PCT * 100)})\n"
        f"Marj: {margin:.2f} USDT | Kaldıraç: {config.LEVERAGE}x\n"
        f"Açık pozisyon: {state.open_position_count()}/{config.MAX_OPEN_POSITIONS}"
    )


def execute_exit(client: BybitClient, state: BotState, symbol: str):
    pos = state.open_positions.get(symbol)
    if not pos:
        return

    order_side = "Buy" if pos["side"] == "long" else "Sell"
    try:
        client.close_position_market(symbol, order_side, str(pos["qty"]))
    except Exception as e:
        notifier.send_message(f"❌ <b>{symbol}</b>\nÇıkış işlemi HATASI: {e}")
        return

    notifier.send_message(
        f"🔚 <b>{symbol}</b> {pos['side'].upper()} pozisyon kapatıldı (Fisher sinyali)\n"
        f"Giriş: {pos['entry_price']}"
    )
    state.remove_position(symbol)


# ---------- Sembol işleme ----------

def process_symbol(client: BybitClient, state: BotState, symbol: str) -> dict:
    """
    Bir coin için tüm işleme adımlarını yürütür.
    Dönüş, tur özeti bildirimi için kategori bilgisi taşır:
        {"symbol": ..., "category": "entered" | "no_signal" | "skipped" | "exited" | "error", "side": ... (opsiyonel)}
    """
    try:
        df_1h = client.get_klines(symbol, config.ENTRY_TIMEFRAME, config.KLINE_LIMIT)
        df_4h = client.get_klines(symbol, config.CONFIRM_TIMEFRAME, config.KLINE_LIMIT)
    except Exception as e:
        print(f"[HATA] {symbol} veri çekilemedi: {e}")
        return {"symbol": symbol, "category": "error"}

    if len(df_1h) < config.EMA_SLOW + 2 or len(df_4h) < config.MACD_SLOW + 2:
        return {"symbol": symbol, "category": "error"}  # yeterli geçmiş veri yok

    signals = strategy.analyze_symbol(df_1h, df_4h)

    has_position = state.has_position(symbol)
    position_side = state.open_positions[symbol]["side"] if has_position else None

    action, payload = strategy.decide(signals, has_position, position_side)

    if action == "exit":
        execute_exit(client, state, symbol)
        # Çıkış sonrası aynı taramada giriş şartları tekrar kontrol edilir
        action2, payload2 = strategy.decide(signals, False, None)
        if action2 == "enter":
            execute_entry(client, state, symbol, payload2, signals["close_price"])
            return {"symbol": symbol, "category": "entered", "side": payload2}
        elif action2 == "skip":
            notifier.send_message(f"⏭️ <b>{symbol}</b>\nÇıkış sonrası yeni giriş atlandı.\nSebep: {payload2}")
            return {"symbol": symbol, "category": "skipped"}
        return {"symbol": symbol, "category": "exited"}

    if action == "enter":
        execute_entry(client, state, symbol, payload, signals["close_price"])
        return {"symbol": symbol, "category": "entered", "side": payload}

    if action == "skip":
        notifier.send_message(f"⏭️ <b>{symbol}</b>\nSinyal atlandı.\nSebep: {payload}")
        return {"symbol": symbol, "category": "skipped"}

    return {"symbol": symbol, "category": "no_signal"}


# ---------- Tur özeti ----------

def send_cycle_summary(state: BotState, results: list):
    """
    Bu turda taranan, işlem açılan ve sinyal gelmeyen coinlerin özetini gönderir.
    (Sinyal gelip de onaylanmayan/atlanan ve çıkış yapılan coinler zaten anlık
    olarak ayrı bildirimlerle bildirilmiş oluyor.)
    """
    scanned = [r["symbol"] for r in results if r["category"] != "error"]
    entered = [f"{r['symbol']} ({r['side'].upper()})" for r in results if r["category"] == "entered"]
    no_signal = [r["symbol"] for r in results if r["category"] == "no_signal"]

    lines = [f"🔍 <b>Tur Özeti</b> (tur #{state.cycle_count})", ""]
    lines.append(f"Taranan ({len(scanned)}): {', '.join(scanned) if scanned else 'Yok'}")
    lines.append("")
    lines.append(f"İşlem açılan ({len(entered)}): {', '.join(entered) if entered else 'Yok'}")
    lines.append("")
    lines.append(f"Sinyal olmayan ({len(no_signal)}): {', '.join(no_signal) if no_signal else 'Yok'}")

    notifier.send_message("\n".join(lines))


# ---------- Durum raporu ----------

def send_status_report(client: BybitClient, state: BotState, label: str):
    try:
        balance = client.get_available_balance()
        balance_line = f"Bakiye: {balance:.2f} USDT"
    except Exception:
        balance_line = "Bakiye alınamadı"

    lines = [
        f"📊 <b>{label} Durum Raporu</b>",
        balance_line,
        f"Açık pozisyon: {state.open_position_count()}/{config.MAX_OPEN_POSITIONS}",
    ]

    if state.open_positions:
        lines.append("")
        for sym, pos in state.open_positions.items():
            lines.append(f"• {sym}: {pos['side'].upper()} | Giriş {pos['entry_price']} | SL {pos['sl_price']}")
    else:
        lines.append("Açık pozisyon yok.")

    notifier.send_message("\n".join(lines))


# ---------- Ana döngü ----------

def main():
    client = BybitClient()
    state = BotState()

    client.ensure_cross_margin()
    notifier.send_message("🤖 Bot başlatıldı. 1 saatlik mum kapanışlarında tarama yapılacak.")

    while True:
        wait_for_next_hour_close(client)
        state.cycle_count += 1

        try:
            reconcile_positions(client, state)
        except Exception as e:
            print(f"[HATA] reconcile_positions: {e}")

        cycle_results = []
        for symbol in config.SYMBOLS:
            try:
                result = process_symbol(client, state, symbol)
            except Exception as e:
                print(f"[HATA] {symbol} işlenirken beklenmeyen hata: {e}")
                result = {"symbol": symbol, "category": "error"}
            cycle_results.append(result)
            time.sleep(config.API_CALL_DELAY_SEC)

        send_cycle_summary(state, cycle_results)

        if state.cycle_count % 24 == 0:
            send_status_report(client, state, "24 Saatlik")
        elif state.cycle_count % 6 == 0:
            send_status_report(client, state, "6 Saatlik")
        else:
            send_status_report(client, state, "Saatlik")


if __name__ == "__main__":
    main()
