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
    "min_buyukluk": "Minimum islem buyuklugu yetersiz",
}

CLOSE_REASONS = {
    "fisher_ters_kesim": "Fisher ters kesim",
    "stop_loss": "Stop-loss tetiklendi",
}

DIR_LABEL = {"long": "LONG", "short": "SHORT", None: "-"}


class TelegramBot:
    """Spec §9: anlik bildirimler + periyodik raporlar. Sayaclar sadece
    bellekte tutulur - spec §8 geregi bot restart'ta her seyi sifirlar,
    bu yuzden hicbir istatistik diske yazilmaz."""

    def __init__(self, bot_manager):
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.bot_manager = bot_manager
        self._lock = threading.Lock()
        self.stats_1h = self._init_stats()
        self.stats_6h = self._init_stats()
        self.stats_24h = self._init_stats()

    def _init_stats(self):
        return {"opened": 0, "closed": 0, "skipped": 0}

    # === GONDERIM ===

    def send(self, text):
        if not self.token or not self.chat_id:
            log.warning("Telegram yapilandirilmamis (token veya chat_id eksik)")
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            resp = req_lib.post(url, json={"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
            if not resp.ok:
                log.error("Telegram gonderim hatasi: %s", resp.text)
        except Exception as e:
            log.error("Telegram gonderim hatasi: %s", e)

    def send_bot_started(self, balance, margin_pct, leverage, coin_count):
        text = (
            "🟢 <b>BOT BASLADI</b>\n"
            f"Zaman: {now_str()}\n"
            f"Izlenen coin: {coin_count}\n"
            f"Bakiye: {format_usdt(balance)} USDT\n"
            f"Marjin: %{margin_pct * 100:.0f} | Kaldirac: {leverage}x\n"
            f"Acik pozisyon: 0 (restart'ta sifirlanir)"
        )
        self.send(text)

    def send_bot_stopped(self, reason, open_count):
        text = (
            "🔴 <b>BOT DURDU</b>\n"
            f"Zaman: {now_str()}\n"
            f"Sebep: {reason}\n"
            f"Bot tarafindan izlenen acik pozisyon: {open_count}"
        )
        self.send(text)

    def send_critical_alert(self, text):
        self.send(f"🆘 <b>KRITIK UYARI</b>\n{text}")

    # spec §9.1
    def send_trade_opened(self, trade):
        with self._lock:
            self.stats_1h["opened"] += 1
            self.stats_6h["opened"] += 1
            self.stats_24h["opened"] += 1
        text = (
            f"{side_emoji(trade['side'])} <b>ISLEM GIRISI</b>\n"
            f"Coin: {trade['symbol']}\n"
            f"Yon: {side_display(trade['side'])}\n"
            f"Giris: {trade['entry_price']:.6f}\n"
            f"Pozisyon Buyuklugu: {format_usdt(trade['margin'])} USDT (marj) | Kaldirac: {trade['leverage']}x\n"
            f"Stop-Loss: {trade['sl_price']:.6f}\n"
            f"Zaman: {now_str()}"
        )
        self.send(text)

    # spec §9.2
    def send_trade_closed(self, close_info):
        with self._lock:
            self.stats_1h["closed"] += 1
            self.stats_6h["closed"] += 1
            self.stats_24h["closed"] += 1
        reason_text = CLOSE_REASONS.get(close_info["reason"], close_info["reason"])
        text = (
            f"{side_emoji(close_info['side'])} <b>ISLEM KAPANISI</b>\n"
            f"Coin: {close_info['symbol']}\n"
            f"Yon: {side_display(close_info['side'])}\n"
            f"Giris: {close_info['entry_price']:.6f} -> Cikis: {close_info['exit_price']:.6f}\n"
            f"Sebep: {reason_text}\n"
            f"Kar/Zarar: {format_pnl(close_info['pnl'], close_info['pnl_pct'])}\n"
            f"Sure: {format_duration(close_info['duration'])}"
        )
        self.send(text)

    # spec §9.3
    def send_signal_mismatch_skip(self, symbol, fisher_dir, ema_dir, macd_dir):
        with self._lock:
            self.stats_1h["skipped"] += 1
            self.stats_6h["skipped"] += 1
            self.stats_24h["skipped"] += 1
        text = (
            f"⚠️ <b>{symbol}</b>\n"
            f"Fisher: {DIR_LABEL[fisher_dir]}\n"
            f"EMA: {DIR_LABEL.get(ema_dir, '-')}\n"
            f"MACD: {DIR_LABEL.get(macd_dir, '-')}\n"
            f"Sinyal atlandi"
        )
        self.send(text)

    # spec §9.4
    def send_signal_skip(self, symbol, side, reason):
        with self._lock:
            self.stats_1h["skipped"] += 1
            self.stats_6h["skipped"] += 1
            self.stats_24h["skipped"] += 1
        text = (
            "⚠️ <b>SINYAL ATLANDI</b>\n"
            f"Coin: {symbol}\n"
            f"Yon: {side_display(side)}\n"
            f"Sebep: {SKIP_REASONS.get(reason, reason)}\n"
            f"Zaman: {now_str()}"
        )
        self.send(text)

    # === PERIYODIK RAPOR (spec §9.5) ===

    def _open_positions_lines(self):
        bm = self.bot_manager
        trades = bm.trade_manager.get_open_trades()
        if not trades:
            return ["Acik pozisyon yok."]
        positions = {(p["symbol"], p["side"]): p for p in bm.bybit.get_positions()}
        lines = []
        for t in trades:
            pos = positions.get((t["symbol"], t["side"]))
            pnl = pos["unrealised_pnl"] if pos else 0.0
            lines.append(f"  {side_emoji(t['side'])} {t['symbol']} {side_display(t['side'])} pnl={format_usdt(pnl)} USDT")
        return lines

    def _send_periodic_report(self, title, stats):
        bm = self.bot_manager
        balance_info = bm.bybit.get_balance()
        balance = balance_info["total"] if balance_info else 0
        open_trades = bm.trade_manager.get_open_trades()
        slot_max = bm.config["global"]["maks_toplam_islem"]

        with self._lock:
            opened, closed, skipped = stats["opened"], stats["closed"], stats["skipped"]

        lines = [
            f"📊 <b>{title}</b>",
            f"Bakiye/Equity: {format_usdt(balance)} USDT",
            f"Donem ici acilan: {opened} | kapanan: {closed} | atlanan sinyal: {skipped}",
            f"Doluluk: {len(open_trades)}/{slot_max}",
            "",
            "Acik Pozisyonlar:",
        ]
        lines.extend(self._open_positions_lines())
        self.send("\n".join(lines))

    def send_1h_report(self):
        self._send_periodic_report("1 SAATLIK RAPOR", self.stats_1h)
        with self._lock:
            self.stats_1h = self._init_stats()

    def send_6h_report(self):
        self._send_periodic_report("6 SAATLIK RAPOR", self.stats_6h)
        with self._lock:
            self.stats_6h = self._init_stats()

    def send_24h_report(self):
        self._send_periodic_report("24 SAATLIK RAPOR", self.stats_24h)
        with self._lock:
            self.stats_24h = self._init_stats()

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
        bm = self.bot_manager
        balance_info = bm.bybit.get_balance()
        balance = balance_info["total"] if balance_info else 0
        used_margin = balance_info["used"] if balance_info else 0

        lines = [
            "📋 <b>ANLIK DURUM RAPORU</b>",
            f"Bakiye: {format_usdt(balance)} USDT",
            f"Kullanilan Marjin: {format_usdt(used_margin)} USDT",
            f"Acik Pozisyon: {bm.trade_manager.get_total_count()}/{bm.config['global']['maks_toplam_islem']}",
            "",
        ]
        lines.extend(self._open_positions_lines())
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
            req_lib.post(f"https://api.telegram.org/bot{self.token}/deleteWebhook", json={"drop_pending_updates": True}, timeout=10)
        except Exception as e:
            log.warning("Webhook silme hatasi: %s", e)
        threading.Thread(target=self._run_polling, daemon=True, name="telegram_polling").start()
        log.info("Telegram polling baslatildi")

    def _run_polling(self):
        commands = {"durum": self.cmd_durum, "yardim": self.cmd_yardim}
        offset = None
        while True:
            try:
                params = {"timeout": 30, "allowed_updates": ["message"]}
                if offset is not None:
                    params["offset"] = offset
                resp = req_lib.get(f"https://api.telegram.org/bot{self.token}/getUpdates", params=params, timeout=40)
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
                    handler = commands.get(cmd)
                    if handler:
                        threading.Thread(target=handler, args=(chat_id, parts[1:]), daemon=True).start()
            except Exception as e:
                log.error("Telegram polling hatasi: %s", e)
                time.sleep(5)
