import time
import threading
from logger_setup import get_logger
from utils import calc_position_size, calc_sl_price, calc_pnl, qty_round_down, generate_order_link_id
import trade_history

log = get_logger("trade_manager")


class TradeManager:
    """Spec §7-8: coin basina en fazla 1, toplamda config.global.maks_toplam_islem
    islem izlenir. Cikis SADECE Fisher ters kesimiyle (close_trade, strategy.py
    tarafindan cagrilir) ya da borsadaki sabit %4 stop-loss'un kendiliginden
    tetiklenmesiyle (poll_exchange_closures) olur. Restart'ta state hic
    yuklenmez/kaydedilmez - bot her zaman 0/maks_toplam_islem ile baslar."""

    def __init__(self, bybit_client, config, telegram=None):
        self.client = bybit_client
        self.config = config
        self.telegram = telegram
        self._lock = threading.Lock()
        self.trades = {}  # symbol -> trade dict
        self._miss_counts = {}  # symbol -> ardisik "borsada bulunamadi" sayaci

    def get_total_count(self):
        with self._lock:
            return len(self.trades)

    def get_trade(self, symbol):
        with self._lock:
            t = self.trades.get(symbol)
            return dict(t) if t else None

    def get_open_trades(self):
        with self._lock:
            return [dict(t) for t in self.trades.values()]

    # === ISLEM ACMA ===

    def open_trade(self, request):
        symbol, side, entry_price = request["symbol"], request["side"], request["entry_price"]
        cfg = self.config.get("global", {})
        max_total = cfg.get("maks_toplam_islem", 5)

        with self._lock:
            already_open = symbol in self.trades
            total = len(self.trades)

        if already_open or total >= max_total:
            log.warning("%s: slot dolu (coin_acik=%s toplam=%d/%d), atlaniyor", symbol, already_open, total, max_total)
            if self.telegram:
                self.telegram.send_signal_skip(symbol, side, "slot_dolu")
            return None

        balance_info = self.client.get_balance()
        if not balance_info:
            log.error("%s %s: Bakiye alinamadi", symbol, side)
            return None

        balance = balance_info["total"]
        margin_pct = cfg.get("marjin_orani", 0.10)
        leverage = cfg.get("kaldirac", 25)

        if not self.client.instrument_info.get(symbol):
            self.client.load_instrument_info([symbol])
            if not self.client.instrument_info.get(symbol):
                log.error("%s: Instrument bilgisi yuklenemedi, islem atlaniyor", symbol)
                return None

        min_qty = self.client.get_min_qty(symbol)
        qty_step = self.client.get_qty_step(symbol)
        qty, margin, notional = calc_position_size(balance, margin_pct, leverage, entry_price)
        rounded_qty = qty_round_down(qty, qty_step)

        if rounded_qty < min_qty:
            log.warning("%s %s: Minimum buyukluk altinda (%.6f < %.6f)", symbol, side, rounded_qty, min_qty)
            if self.telegram:
                self.telegram.send_signal_skip(symbol, side, "min_buyukluk")
            return None

        if margin > balance_info["available"]:
            log.warning("%s %s: Yetersiz bakiye (%.2f > %.2f)", symbol, side, margin, balance_info["available"])
            if self.telegram:
                self.telegram.send_signal_skip(symbol, side, "bakiye_yetersiz")
            return None

        max_retries = cfg.get("islem_deneme", 3)
        retry_delay = cfg.get("islem_acma_bekleme_sn", 2)
        order_link_id = generate_order_link_id(side, symbol)

        result = None
        for attempt in range(1, max_retries + 1):
            result = self.client.place_order(symbol=symbol, side=side, qty=rounded_qty, order_link_id=order_link_id)
            if result["success"]:
                break
            log.warning("%s %s: Emir denemesi %d/%d basarisiz: %s", symbol, side, attempt, max_retries, result.get("error", ""))
            if attempt < max_retries:
                time.sleep(retry_delay)

        if not result or not result["success"]:
            log.error("%s %s: %d deneme basarisiz, sinyal atlaniyor", symbol, side, max_retries)
            if self.telegram:
                self.telegram.send_signal_skip(symbol, side, "emir_hatasi")
            return None

        actual_qty = result["qty"]
        actual_margin = (actual_qty * entry_price) / leverage
        sl_price = self._set_stop_loss(symbol, side, entry_price)

        trade = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "qty": actual_qty,
            "sl_price": sl_price,
            "margin": actual_margin,
            "leverage": leverage,
            "order_id": result["order_id"],
            "open_time": time.time(),
        }

        with self._lock:
            self.trades[symbol] = trade
            self._miss_counts[symbol] = 0

        log.info("ISLEM ACILDI: %s %s giris=%.6f sl=%.6f qty=%.6f", symbol, side, entry_price, sl_price, actual_qty)
        if self.telegram:
            self.telegram.send_trade_opened(trade)
        return trade

    def _set_stop_loss(self, symbol, side, entry_price):
        """Spec §7: borsaya sabit %4 stop-loss - mum kapanislari arasindaki
        TEK koruma. Basarisiz olursa 3 kez denenir, hepsi basarisizsa
        kritik Telegram uyarisi gonderilir."""
        sl_pct = self.config.get("global", {}).get("sl_orani", 0.04)
        sl_price = calc_sl_price(entry_price, sl_pct, side)

        for attempt in range(1, 4):
            if self.client.set_position_sl(symbol, side, sl_price):
                return sl_price
            log.warning("%s %s: SL koyma denemesi %d/3 basarisiz", symbol, side, attempt)
            if attempt < 3:
                time.sleep(1)

        log.error("%s %s: SL 3 denemede de konulamadi, pozisyon korumasiz!", symbol, side)
        if self.telegram:
            self.telegram.send_critical_alert(
                f"{symbol} {side.upper()}: Stop-loss borsaya YERLESTIRILEMEDI. "
                f"Pozisyon korumasiz, lutfen manuel kontrol edin."
            )
        return sl_price

    # === ISLEM KAPATMA: Fisher ters kesim (strategy.py tarafindan cagrilir) ===

    def close_trade(self, symbol, reason, exit_price):
        with self._lock:
            trade = self.trades.get(symbol)
        if not trade:
            return None

        cfg = self.config.get("global", {})
        max_retries = cfg.get("islem_deneme", 3)
        retry_delay = cfg.get("islem_kapatma_bekleme_sn", 2)

        # Borsadaki guncel pozisyon miktari kapatilir (bot'un izledigi qty degil).
        exchange_qty = self.client.get_position_size(symbol, trade["side"])
        close_qty = exchange_qty if exchange_qty > 0 else trade["qty"]

        result = None
        for attempt in range(1, max_retries + 1):
            result = self.client.close_position(symbol, trade["side"], close_qty)
            if result["success"]:
                break
            log.warning("%s %s: Kapatma denemesi %d/%d basarisiz: %s", symbol, trade["side"], attempt, max_retries, result.get("error", ""))
            if attempt < max_retries:
                time.sleep(retry_delay)

        if not result or not result["success"]:
            log.error("%s %s: Kapatma basarisiz (%s), pozisyon acik kaliyor", symbol, trade["side"], reason)
            return None

        self._finalize_close(trade, reason, exit_price)
        return trade

    def _finalize_close(self, trade, reason, exit_price):
        pnl, pnl_pct = calc_pnl(trade["entry_price"], exit_price, trade["qty"], trade["side"], trade["margin"])
        duration = time.time() - trade["open_time"]

        with self._lock:
            self.trades.pop(trade["symbol"], None)
            self._miss_counts.pop(trade["symbol"], None)

        trade_history.record(trade["symbol"], trade["side"], trade["entry_price"], exit_price, trade["qty"], pnl, reason)

        close_info = {
            "symbol": trade["symbol"], "side": trade["side"], "entry_price": trade["entry_price"],
            "exit_price": exit_price, "qty": trade["qty"], "pnl": pnl, "pnl_pct": pnl_pct,
            "duration": duration, "reason": reason,
        }

        log.info("ISLEM KAPANDI: %s %s cikis=%.6f pnl=%.2f (%s)", trade["symbol"], trade["side"], exit_price, pnl, reason)
        if self.telegram:
            self.telegram.send_trade_closed(close_info)

    # === BORSA-TARAFLI KAPANIS ALGILAMA (spec §7: %4 SL kendiliginden tetiklenmesi) ===

    def poll_exchange_closures(self):
        """Cikis normalde sadece 1H mum kapanisinda Fisher ile olur; borsadaki
        sabit %4 SL ise mumlar arasinda herhangi bir an tetiklenebilir. Bunu
        algilamak icin takip edilen pozisyonlarin hala borsada olup olmadigi
        kontrol edilir. 2 ardisik kayip sonrasi SL tetiklenmis kabul edilir
        (gecici/eksik API yanitina karsi debounce)."""
        with self._lock:
            tracked = {s: dict(t) for s, t in self.trades.items()}
        if not tracked:
            return

        present = {(p["symbol"], p["side"]) for p in self.client.get_positions()}

        for symbol, trade in tracked.items():
            key = (symbol, trade["side"])
            if key in present:
                self._miss_counts[symbol] = 0
                continue
            self._miss_counts[symbol] = self._miss_counts.get(symbol, 0) + 1
            if self._miss_counts[symbol] >= 2:
                self._handle_sl_closure(trade)

    def _handle_sl_closure(self, trade):
        symbol = trade["symbol"]
        with self._lock:
            if symbol not in self.trades:
                return

        exit_price = trade["sl_price"]
        try:
            closed = self.client.get_closed_pnl(symbol=symbol, limit=5)
            bybit_side = "Buy" if trade["side"] == "long" else "Sell"
            for c in closed:
                if c.get("side") != bybit_side:
                    continue
                if int(c.get("updatedTime", 0)) >= int(trade["open_time"] * 1000):
                    if c.get("avgExitPrice"):
                        exit_price = float(c["avgExitPrice"])
                    break
        except Exception as e:
            log.warning("%s: get_closed_pnl okunamadi, sl_price ile hesaplanacak: %s", symbol, e)

        log.info("STOP-LOSS TETIKLENDI: %s %s cikis~=%.6f", symbol, trade["side"], exit_price)
        self._finalize_close(trade, "stop_loss", exit_price)
