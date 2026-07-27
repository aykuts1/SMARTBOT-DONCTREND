import time
import threading
from logger_setup import get_logger
from utils import (
    calc_position_size, calc_sl_price, calc_pnl, sl_round,
    qty_round_down, generate_order_link_id
)
import trade_history

log = get_logger("trade_manager")


class TradeManager:
    """Spesifikasyon §8-9-11-12: sanal islem takibi.

    Ayni coin+yonde birden fazla islem borsada TEK pozisyonda toplanir
    (Bybit hedge modu); bot her sinyali kendi entry/lose/win seviyeleriyle
    ayri 'sanal islem' olarak izler ve kapanislari reduce-only kismi
    emirlerle yapar. Pozisyonun tamamini kapsayan %5 emniyet SL'i her yeni
    girise gore guncellenir.
    """

    def __init__(self, bybit_client, config, telegram=None, on_state_change=None):
        self.client = bybit_client
        self.config = config
        self.telegram = telegram
        self._on_state_change = on_state_change
        self._lock = threading.Lock()
        self.trades = []
        self._next_id = 1

    def reload_config(self, config):
        self.config = config

    def _persist(self):
        if self._on_state_change:
            self._on_state_change()

    def get_total_count(self):
        with self._lock:
            return len(self.trades)

    def get_coin_count(self, symbol):
        with self._lock:
            return sum(1 for t in self.trades if t["symbol"] == symbol)

    def get_open_trades(self, symbol=None):
        with self._lock:
            if symbol:
                return [dict(t) for t in self.trades if t["symbol"] == symbol]
            return [dict(t) for t in self.trades]

    def get_trades_for_symbol_side(self, symbol, side):
        with self._lock:
            return [t for t in self.trades if t["symbol"] == symbol and t["side"] == side]

    # === ISLEM ACMA ===

    def open_trade(self, request):
        symbol = request["symbol"]
        side = request["side"]
        entry_price = request["entry_price"]
        lose_exit = request["lose_exit"]
        win_exit = request["win_exit"]

        cfg = self.config.get("global", {})
        max_total = cfg.get("max_toplam_islem", 20)
        max_per_coin_side = cfg.get("max_coin_yon_basi_islem", 2)

        with self._lock:
            total = len(self.trades)
            coin_side_count = sum(1 for t in self.trades if t["symbol"] == symbol and t["side"] == side)

        if total >= max_total:
            log.warning("Toplam slot dolu (%d/%d), %s %s atlaniyor", total, max_total, symbol, side)
            if self.telegram:
                self.telegram.send_signal_skip(symbol, side, "slot_dolu")
            return None

        if coin_side_count >= max_per_coin_side:
            log.warning("%s %s slot dolu (%d/%d), atlaniyor", symbol, side, coin_side_count, max_per_coin_side)
            if self.telegram:
                self.telegram.send_signal_skip(symbol, side, "slot_dolu")
            return None

        balance_info = self.client.get_balance()
        if not balance_info:
            log.error("%s %s: Bakiye alinamadi", symbol, side)
            return None

        balance = balance_info["total"]
        margin_pct = cfg.get("marjin_orani", 0.05)
        leverage = cfg.get("kaldirac", 20)

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
            log.warning("%s %s: Minimum buyukluk altinda (%.6f < %.6f)",
                        symbol, side, rounded_qty, min_qty)
            if self.telegram:
                self.telegram.send_signal_skip(symbol, side, "min_buyukluk")
            return None

        if margin > balance_info["available"]:
            log.warning("%s %s: Yetersiz bakiye (%.2f > %.2f)",
                        symbol, side, margin, balance_info["available"])
            if self.telegram:
                self.telegram.send_signal_skip(symbol, side, "bakiye_yetersiz")
            return None

        max_retries = cfg.get("islem_acma_deneme", 3)
        retry_delay = cfg.get("islem_acma_bekleme_sn", 2)
        order_link_id = generate_order_link_id(side, symbol)

        result = None
        for attempt in range(1, max_retries + 1):
            result = self.client.place_order(
                symbol=symbol, side=side, qty=rounded_qty, order_link_id=order_link_id
            )
            if result["success"]:
                break
            log.warning("%s %s: Emir denemesi %d/%d basarisiz: %s",
                        symbol, side, attempt, max_retries, result.get("error", ""))
            if attempt < max_retries:
                time.sleep(retry_delay)

        if not result or not result["success"]:
            log.error("%s %s: %d deneme basarisiz, sinyal atlaniyor", symbol, side, max_retries)
            if self.telegram:
                self.telegram.send_signal_skip(symbol, side, "emir_hatasi")
            return None

        actual_notional = rounded_qty * entry_price
        commission = actual_notional * 0.00055
        actual_margin = actual_notional / leverage

        self._refresh_safety_sl(symbol, side, entry_price)

        trade = {
            "id": None,
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "qty": rounded_qty,
            "lose_exit": lose_exit,
            "win_exit": win_exit,
            "margin": actual_margin,
            "leverage": leverage,
            "commission": commission,
            "order_id": result["order_id"],
            "order_link_id": order_link_id,
            "open_time": time.time(),
        }

        with self._lock:
            trade["id"] = self._next_id
            self._next_id += 1
            self.trades.append(trade)

        self._persist()

        log.info("ISLEM ACILDI: %s %s giris=%.6f lose=%.6f win=%.6f qty=%.6f",
                  symbol, side, entry_price, lose_exit, win_exit, rounded_qty)

        if self.telegram:
            self.telegram.send_trade_opened(trade)

        return trade

    def _refresh_safety_sl(self, symbol, side, latest_entry_price):
        """Spec §9: borsaya %5 emniyet SL emri - sadece emniyet kemeri.
        Pozisyonun tamamini kapsayacak sekilde en son giris fiyatina gore guncellenir."""
        cfg = self.config.get("global", {})
        safety_pct = cfg.get("guvenlik_sl_orani", 0.05)
        sl_price = calc_sl_price(latest_entry_price, safety_pct, side)
        tick_size = self.client.get_tick_size(symbol)
        sl_price = sl_round(0, sl_price, tick_size, side)
        self.client.set_position_sl(symbol, side, sl_price)

    # === ISLEM KAPATMA (5sn tick, spec §6) ===

    def check_exit(self, symbol, price):
        if not price or price <= 0:
            return
        with self._lock:
            symbol_trades = [t for t in self.trades if t["symbol"] == symbol]

        for trade in symbol_trades:
            reason = None
            if trade["side"] == "long":
                if price <= trade["lose_exit"]:
                    reason = "lose_exit"
                elif price >= trade["win_exit"]:
                    reason = "win_exit"
            else:
                if price >= trade["lose_exit"]:
                    reason = "lose_exit"
                elif price <= trade["win_exit"]:
                    reason = "win_exit"

            if reason:
                self._close_trade(trade, reason, price)

    def _close_trade(self, trade, reason, exit_price):
        cfg = self.config.get("global", {})
        max_retries = cfg.get("islem_acma_deneme", 3)
        retry_delay = cfg.get("islem_kapatma_bekleme_sn", 2)

        result = None
        for attempt in range(1, max_retries + 1):
            result = self.client.close_position(trade["symbol"], trade["side"], trade["qty"])
            if result["success"]:
                break
            log.warning("%s %s: Kapatma denemesi %d/%d basarisiz: %s",
                        trade["symbol"], trade["side"], attempt, max_retries, result.get("error", ""))
            if attempt < max_retries:
                time.sleep(retry_delay)

        if not result or not result["success"]:
            log.error("%s %s: Kapatma basarisiz (%s), sonraki tick'te tekrar denenecek",
                      trade["symbol"], trade["side"], reason)
            return

        pnl, pnl_pct = calc_pnl(trade["entry_price"], exit_price, trade["qty"], trade["side"])
        duration = time.time() - trade["open_time"]
        close_commission = abs(exit_price * trade["qty"]) * 0.00055
        total_commission = trade["commission"] + close_commission

        with self._lock:
            self.trades = [t for t in self.trades if t["id"] != trade["id"]]

        self._persist()

        trade_history.record(
            trade["symbol"], trade["side"], trade["entry_price"], exit_price,
            trade["qty"], pnl, reason
        )

        close_info = {
            "symbol": trade["symbol"],
            "side": trade["side"],
            "entry_price": trade["entry_price"],
            "exit_price": exit_price,
            "qty": trade["qty"],
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "duration": duration,
            "reason": reason,
            "commission": total_commission,
        }

        log.info("ISLEM KAPANDI: %s %s cikis=%.6f pnl=%.2f (%s)",
                  trade["symbol"], trade["side"], exit_price, pnl, reason)

        if self.telegram:
            self.telegram.send_trade_closed(close_info)

    # === RECONCILIATION ===

    def reconcile(self):
        """Borsadaki gercek pozisyonlarla sanal islem toplamlarini karsilastirir,
        buyuk sapma varsa gorunurluk icin uyarir (otomatik duzeltme yapmaz)."""
        positions = self.client.get_positions()
        with self._lock:
            internal_totals = {}
            for t in self.trades:
                key = (t["symbol"], t["side"])
                internal_totals[key] = internal_totals.get(key, 0.0) + t["qty"]

        exchange_totals = {}
        for pos in positions:
            key = (pos["symbol"], pos["side"])
            exchange_totals[key] = exchange_totals.get(key, 0.0) + pos["size"]

        all_keys = set(internal_totals) | set(exchange_totals)
        for key in all_keys:
            internal_qty = internal_totals.get(key, 0.0)
            exchange_qty = exchange_totals.get(key, 0.0)
            if abs(internal_qty - exchange_qty) > max(internal_qty, exchange_qty) * 0.01 + 1e-9:
                symbol, side = key
                log.warning("Uyusmazlik: %s %s bot=%.6f borsa=%.6f", symbol, side, internal_qty, exchange_qty)
                if self.telegram:
                    self.telegram.send_reconcile_warning(symbol, side, internal_qty, exchange_qty)

    # === STATE PERSISTENCE ===

    def to_dict(self):
        with self._lock:
            return {"trades": [dict(t) for t in self.trades], "next_id": self._next_id}

    def from_dict(self, data):
        with self._lock:
            self.trades = list((data or {}).get("trades", []))
            self._next_id = (data or {}).get("next_id", 1)
