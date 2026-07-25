import os
import time
import threading
import requests as req_lib
from logger_setup import get_logger
from utils import format_usdt, format_pnl, format_duration, now_str, side_emoji, side_display

log = get_logger("telegram")

SKIP_REASONS = {
    "slot_dolu": "Slot dolu",
    "bakiye_yetersiz": "Bakiye yetersiz",
    "emir_hatasi": "Emir hatasi",
}


class TelegramBot:
    def __init__(self, bot_manager=None):
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.bot_manager = bot_manager
        self._lock = threading.Lock()

        self.stats_1h = self._init_stats()
        self.stats_6h = self._init_stats()
        self.stats_24h = self._init_stats()

    def _init_stats(self):
        return {
            "opened": 0, "closed": 0, "skipped": 0,
            "wins": 0, "losses": 0, "pnl": 0.0,
            "coin_stats": {},
        }

    def _coin_stats(self, stats, symbol):
        if symbol not in stats["coin_stats"]:
            stats["coin_stats"][symbol] = {"opened": 0, "closed": 0, "wins": 0, "losses": 0, "pnl": 0.0}
        return stats["coin_stats"][symbol]

    # === KAYIT (istatistik sayaclari) ===

    def record_open(self, symbol):
        with self._lock:
            for stats in (self.stats_1h, self.stats_6h, self.stats_24h):
                stats["opened"] += 1
                self._coin_stats(stats, symbol)["opened"] += 1

    def record_close(self, symbol, pnl):
        with self._lock:
            for stats in (self.stats_1h, self.stats_6h, self.stats_24h):
                stats["closed"] += 1
                stats["pnl"] += pnl
                coin = self._coin_stats(stats, symbol)
                coin["closed"] += 1
                coin["pnl"] += pnl
                if pnl >= 0:
                    stats["wins"] += 1
                    coin["wins"] += 1
                else:
                    stats["losses"] += 1
                    coin["losses"] += 1

    def record_skip(self):
        with self._lock:
            for stats in (self.stats_1h, self.stats_6h, self.stats_24h):
                stats["skipped"] += 1

    # === GONDERIM ===

    def send(self, text):
        if not self.token or not self.chat_id:
            log.warning("Telegram yapilandirilmamis (token veya chat_id eksik)")
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
            resp = req_lib.post(url, json=payload, timeout=10)
            if not resp.ok:
                log.error("Telegram gonderim hatasi: %s", resp.text)
        except Exception as e:
            log.error("Telegram gonderim hatasi: %s", e)

    def send_bot_started(self, balance, margin_pct, leverage, coin_count, open_count):
        text = (
            "🟢 <b>BOT BASLADI</b>\n"
            f"Zaman: {now_str()}\n"
            f"Izlenen coin: {coin_count}\n"
            f"Bakiye: {format_usdt(balance)} USDT\n"
            f"Marjin: %{margin_pct * 100:.0f} | Kaldirac: {leverage}x\n"
            f"Acik pozisyon: {open_count}"
        )
        self.send(text)

    def send_bot_stopped(self, reason, open_count):
        text = (
            "🔴 <b>BOT DURDU</b>\n"
            f"Zaman: {now_str()}\n"
            f"Sebep: {reason}\n"
            f"Acik pozisyon: {open_count}"
        )
        self.send(text)

    def send_signal_skip(self, symbol, side, reason):
        self.record_skip()
        reason_text = SKIP_REASONS.get(reason, reason)
        text = (
            "⚠️ <b>SINYAL ATLANDI</b>\n"
            f"Coin: {symbol}\n"
            f"Yon: {side_display(side)}\n"
            f"Sebep: {reason_text}\n"
            f"Zaman: {now_str()}"
        )
        self.send(text)

    def send_trade_opened(self, trade):
        self.record_open(trade["symbol"])
        text = (
            f"{side_emoji(trade['side'])} <b>ISLEM GIRISI</b>\n"
            f"Coin: {trade['symbol']}\n"
            f"Yon: {side_display(trade['side'])}\n"
            f"Giris: {trade['entry_price']:.6f}\n"
            f"Lose Exit: {trade['lose_exit']:.6f}\n"
            f"Win Exit: {trade['win_exit']:.6f}\n"
            f"Marjin: {format_usdt(trade['margin'])} USDT | Kaldirac: {trade['leverage']}x\n"
            f"Zaman: {now_str()}"
        )
        self.send(text)

    def send_trade_closed(self, close_info):
        self.record_close(close_info["symbol"], close_info["pnl"])
        text = (
            f"{side_emoji(close_info['side'])} <b>ISLEM KAPANISI</b>\n"
            f"Coin: {close_info['symbol']}\n"
            f"Yon: {side_display(close_info['side'])}\n"
            f"Giris: {close_info['entry_price']:.6f} -> Cikis: {close_info['exit_price']:.6f}\n"
            f"Sebep: {close_info['reason']}\n"
            f"Kar/Zarar: {format_pnl(close_info['pnl'], close_info['pnl_pct'])}\n"
            f"Sure: {format_duration(close_info['duration'])}"
        )
        self.send(text)

    def send_reconcile_warning(self, symbol, side, internal_qty, exchange_qty):
        text = (
            "⚠️ <b>POZISYON UYUSMAZLIGI</b>\n"
            f"Coin: {symbol} | Yon: {side_display(side)}\n"
            f"Bot takibi: {internal_qty:.6f}\n"
            f"Borsadaki: {exchange_qty:.6f}"
        )
        self.send(text)

    # === PERIYODIK RAPORLAR ===

    def send_hourly_report(self, balance, open_count):
        with self._lock:
            stats = self.stats_1h
            text = (
                "📊 <b>1 SAATLIK RAPOR</b>\n"
                f"Acilan islem: {stats['opened']}\n"
                f"Kapanan islem: {stats['closed']}\n"
                f"Atlanan sinyal: {stats['skipped']}\n"
                f"Acik pozisyon: {open_count}\n"
                f"Bakiye: {format_usdt(balance)} USDT"
            )
            self.stats_1h = self._init_stats()
        self.send(text)

    def send_6h_report(self, balance):
        with self._lock:
            stats = self.stats_6h
            total_closed = stats["wins"] + stats["losses"]
            win_rate = (stats["wins"] / total_closed * 100) if total_closed else 0.0
            lines = [
                "📊 <b>6 SAATLIK RAPOR</b>",
                f"Acilan: {stats['opened']} | Kapanan: {stats['closed']} | Atlanan: {stats['skipped']}",
                f"Donemsel Win Rate: %{win_rate:.1f}",
                f"Toplam Kar/Zarar: {format_usdt(stats['pnl'])} USDT",
                f"Bakiye: {format_usdt(balance)} USDT",
                "",
                "Coin Bazli Dagilim:",
            ]
            for symbol, cs in sorted(stats["coin_stats"].items()):
                if cs["opened"] or cs["closed"]:
                    lines.append(f"  {symbol}: acilan={cs['opened']} kapanan={cs['closed']} pnl={format_usdt(cs['pnl'])}")
            text = "\n".join(lines)
            self.stats_6h = self._init_stats()
        self.send(text)

    def send_24h_report(self, balance):
        with self._lock:
            stats = self.stats_24h
            total_closed = stats["wins"] + stats["losses"]
            win_rate = (stats["wins"] / total_closed * 100) if total_closed else 0.0
            best_coin = None
            best_count = 0
            for symbol, cs in stats["coin_stats"].items():
                if cs["opened"] > best_count:
                    best_count = cs["opened"]
                    best_coin = symbol
            text = (
                "📊 <b>24 SAATLIK RAPOR</b>\n"
                f"Toplam Kar/Zarar: {format_usdt(stats['pnl'])} USDT\n"
                f"Win Rate: %{win_rate:.1f}\n"
                f"En Aktif Coin: {best_coin or '-'}\n"
                f"Acilan Sinyal: {stats['opened']} | Atlanan Sinyal: {stats['skipped']}\n"
                f"Bakiye: {format_usdt(balance)} USDT"
            )
            self.stats_24h = self._init_stats()
        self.send(text)

    # === STATE PERSISTENCE ===

    def to_dict(self):
        with self._lock:
            return {"stats_1h": self.stats_1h, "stats_6h": self.stats_6h, "stats_24h": self.stats_24h}

    def from_dict(self, data):
        with self._lock:
            data = data or {}
            self.stats_1h = data.get("stats_1h") or self._init_stats()
            self.stats_6h = data.get("stats_6h") or self._init_stats()
            self.stats_24h = data.get("stats_24h") or self._init_stats()

    # === KOMUTLAR (/durum, /yardim) ===

    def _reply(self, chat_id, text):
        if not self.token:
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            req_lib.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
        except Exception as e:
            log.error("Telegram yanit hatasi: %s", e)

    def cmd_durum(self, chat_id, args):
        if not self.bot_manager:
            self._reply(chat_id, "Bot henuz hazir degil.")
            return
        bm = self.bot_manager
        balance_info = bm.bybit.get_balance()
        balance = balance_info["total"] if balance_info else 0
        used_margin = balance_info["used"] if balance_info else 0
        trades = bm.trade_manager.get_open_trades()

        lines = [
            "📋 <b>ANLIK DURUM RAPORU</b>",
            f"Bakiye: {format_usdt(balance)} USDT",
            f"Kullanilan Marjin: {format_usdt(used_margin)} USDT",
            f"Acik Pozisyon: {len(trades)}",
            "",
        ]
        for t in trades:
            price = bm.data_pool.get_price(t["symbol"])
            pnl = 0.0
            if price:
                if t["side"] == "long":
                    pnl = (price - t["entry_price"]) * t["qty"]
                else:
                    pnl = (t["entry_price"] - price) * t["qty"]
            lines.append(
                f"{side_emoji(t['side'])} {t['symbol']} {side_display(t['side'])} "
                f"giris={t['entry_price']:.6f} pnl={format_usdt(pnl)}"
            )
        self._reply(chat_id, "\n".join(lines))

    def cmd_yardim(self, chat_id, args):
        text = (
            "<b>Komutlar</b>\n"
            "/durum - Anlik durum raporu (acik pozisyonlar, bakiye, marjin)\n"
            "/yardim - Bu mesaj"
        )
        self._reply(chat_id, text)

    def start_polling(self):
        if not self.token:
            log.warning("Telegram token bulunamadi, komutlar devre disi")
            return
        try:
            req_lib.post(
                f"https://api.telegram.org/bot{self.token}/deleteWebhook",
                json={"drop_pending_updates": True}, timeout=10
            )
        except Exception as e:
            log.warning("Webhook silme hatasi: %s", e)
        thread = threading.Thread(target=self._run_polling, daemon=True, name="telegram_polling")
        thread.start()
        log.info("Telegram polling baslatildi")

    def _run_polling(self):
        commands = {"durum": self.cmd_durum, "yardim": self.cmd_yardim}
        offset = None
        log.info("Telegram getUpdates dongusu basladi")
        while True:
            try:
                params = {"timeout": 30, "allowed_updates": ["message"]}
                if offset is not None:
                    params["offset"] = offset
                resp = req_lib.get(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    params=params, timeout=40
                )
                if not resp.ok:
                    log.warning("getUpdates hatasi: %s", resp.text)
                    time.sleep(5)
                    continue
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    chat_id = msg.get("chat", {}).get("id")
                    if not text or not chat_id or not text.startswith("/"):
                        continue
                    parts = text.split()
                    cmd = parts[0].split("@")[0][1:].lower()
                    args = parts[1:]
                    log.info("Komut alindi: /%s (chat_id=%s)", cmd, chat_id)
                    handler = commands.get(cmd)
                    if handler:
                        threading.Thread(target=handler, args=(chat_id, args), daemon=True).start()
            except Exception as e:
                log.error("Telegram polling hatasi: %s", e)
                time.sleep(5)
