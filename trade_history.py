import json
import os
import time
import threading

_lock = threading.Lock()
_FILE = "trade_history.json"
_MAX = 500


def record(symbol, side, entry_price, exit_price, qty, pnl, reason):
    entry = {
        "time": time.time(),
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "qty": qty,
        "pnl": pnl,
        "reason": reason,
    }
    with _lock:
        records = _load()
        records.append(entry)
        if len(records) > _MAX:
            records = records[-_MAX:]
        _save(records)


def get_last(n=100):
    with _lock:
        records = _load()
    return list(reversed(records[-n:])) if records else []


def _load():
    if not os.path.exists(_FILE):
        return []
    try:
        with open(_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(records):
    try:
        with open(_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        pass
