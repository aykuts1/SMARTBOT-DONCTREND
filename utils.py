import time
import json
import os
from decimal import Decimal, ROUND_DOWN, ROUND_UP, ROUND_HALF_UP
from datetime import datetime
from logger_setup import get_logger

log = get_logger("utils")

ORDER_PREFIX = "BOT"


def load_config(path="config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_config_mtime(path="config.json"):
    return os.path.getmtime(path)


def format_usdt(value):
    if abs(value) >= 1:
        return f"{value:,.2f}"
    else:
        return f"{value:.6f}"


def format_pnl(pnl_usdt, pnl_pct):
    sign_usdt = "+" if pnl_usdt >= 0 else "-"
    sign_pct = "+" if pnl_pct >= 0 else "-"
    icon = "✅" if pnl_usdt >= 0 else "❌"
    return f"{sign_usdt}{format_usdt(abs(pnl_usdt))} USDT  |  {sign_pct}%{abs(pnl_pct):.2f}  {icon}"


def format_duration(seconds):
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}s {minutes:02d}dk"


def now_str():
    return datetime.now().strftime("%H:%M | %d.%m.%Y")


def now_ts():
    return int(time.time() * 1000)


def tick_round(value, tick_size, direction="nearest"):
    if tick_size <= 0:
        return value
    d_val = Decimal(str(value))
    d_tick = Decimal(str(tick_size))
    if direction == "down":
        steps = (d_val / d_tick).to_integral_value(rounding=ROUND_DOWN)
    elif direction == "up":
        steps = (d_val / d_tick).to_integral_value(rounding=ROUND_UP)
    else:
        steps = (d_val / d_tick).to_integral_value(rounding=ROUND_HALF_UP)
    return float(steps * d_tick)


def qty_round_down(qty, step_size):
    if step_size <= 0:
        return qty
    d_qty = Decimal(str(qty))
    d_step = Decimal(str(step_size))
    steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
    return float(steps * d_step)


def qty_to_str(qty, qty_step):
    """Bybit API için qty'yi doğru ondalık basamakta string'e çevirir."""
    d_step = Decimal(str(qty_step))
    d_qty = Decimal(str(qty))
    return str(d_qty.quantize(d_step))


def price_to_str(price, tick_size):
    """Bybit API için fiyatı doğru ondalık basamakta string'e çevirir."""
    d_tick = Decimal(str(tick_size))
    d_price = Decimal(str(price))
    return str(d_price.quantize(d_tick))


def sl_round(entry_price, sl_price, tick_size, side):
    if side == "short":
        return tick_round(sl_price, tick_size, "up")
    else:
        return tick_round(sl_price, tick_size, "down")


def calc_sl_price(entry_price, sl_pct, side):
    if side == "short":
        return entry_price * (1 + sl_pct)
    else:
        return entry_price * (1 - sl_pct)


def calc_position_size(balance, margin_pct, leverage, price):
    margin = balance * margin_pct
    notional = margin * leverage
    qty = notional / price
    return qty, margin, notional


def calc_pnl(entry_price, exit_price, qty, side):
    if side == "short":
        pnl = (entry_price - exit_price) * qty
    else:
        pnl = (exit_price - entry_price) * qty
    pnl_pct = (pnl / (entry_price * qty)) * 100 if entry_price * qty > 0 else 0
    return pnl, pnl_pct


def generate_order_link_id(side, symbol):
    ts = int(time.time() * 1000)
    return f"{ORDER_PREFIX}_{side}_{symbol}_{ts}"


def parse_order_link_id(order_link_id):
    try:
        parts = order_link_id.split("_")
        if len(parts) >= 4:
            return {
                "side": parts[1],
                "symbol": parts[2],
                "timestamp": parts[3]
            }
    except Exception:
        pass
    return None


def is_our_order(order_link_id):
    if not order_link_id:
        return False
    prefix = order_link_id.split("_")[0] if "_" in order_link_id else ""
    return prefix == ORDER_PREFIX


def side_emoji(side):
    return "📈" if side == "long" else "📉"


def side_display(side):
    return "LONG" if side == "long" else "SHORT"
