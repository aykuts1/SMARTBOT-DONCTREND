import json
import os
import threading
from logger_setup import get_logger

log = get_logger("state_store")

_lock = threading.Lock()
_FILE = "bot_state.json"


def load():
    if not os.path.exists(_FILE):
        return {}
    try:
        with _lock:
            with open(_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        log.error("State yuklenemedi: %s", e)
        return {}


def save(data):
    """Atomic write: once tmp dosyaya yazip os.replace ile degistirir,
    yaziyorken bot crash olursa bot_state.json bozulmasin diye."""
    try:
        with _lock:
            tmp_path = _FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp_path, _FILE)
    except Exception as e:
        log.error("State kaydedilemedi: %s", e)
