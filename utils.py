import time
import json
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from datetime import datetime

ORDER_PREFIX = "BOT"


def load_config(path="config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_usdt(value):
    if abs(value) >= 1:
        return f"{value:,.2f}"
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


def tick_round(value, tick_size, direction="nearest"):
    if tick_size <= 0:
        return value
    d_val = Decimal(str(value))
    d_tick = Decimal(str(tick_size))
    rounding = {"down": ROUND_DOWN, "up": ROUND_UP}.get(direction, ROUND_DOWN)
    steps = (d_val / d_tick).to_integral_value(rounding=rounding)
    return float(steps * d_tick)


def qty_round_down(qty, step_size):
    if step_size <= 0:
        return qty
    d_qty = Decimal(str(qty))
    d_step = Decimal(str(step_size))
    steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
    return float(steps * d_step)


def qty_to_str(qty, qty_step):
    d_step = Decimal(str(qty_step))
    d_qty = Decimal(str(qty))
    return str(d_qty.quantize(d_step))


def price_to_str(price, tick_size):
    d_tick = Decimal(str(tick_size))
    d_price = Decimal(str(price))
    return str(d_price.quantize(d_tick))


def sl_round(sl_price, tick_size, side):
    """SL her zaman istenen mesafenin en az kadar uzaginda kalsin diye,
    long icin asagi (SL'i daha da uzaklastirir), short icin yukari
    (SL'i daha da uzaklastirir) yuvarlanir."""
    if side == "short":
        return tick_round(sl_price, tick_size, "up")
    return tick_round(sl_price, tick_size, "down")


def calc_sl_price(entry_price, sl_pct, side):
    if side == "short":
        return entry_price * (1 + sl_pct)
    return entry_price * (1 - sl_pct)


def calc_position_size(balance, margin_pct, leverage, price):
    """Spec §7: pozisyon buyuklugu = bakiyenin %10'u (marj), 25x kaldirac ile
    acilan notional = marj * kaldirac."""
    margin = balance * margin_pct
    notional = margin * leverage
    qty = notional / price
    return qty, margin, notional


def calc_pnl(entry_price, exit_price, qty, side, margin):
    if side == "short":
        pnl = (entry_price - exit_price) * qty
    else:
        pnl = (exit_price - entry_price) * qty
    pnl_pct = (pnl / margin * 100) if margin > 0 else 0.0
    return pnl, pnl_pct


def generate_order_link_id(side, symbol):
    ts = int(time.time() * 1000)
    return f"{ORDER_PREFIX}_{side}_{symbol}_{ts}"


def side_emoji(side):
    return "📈" if side == "long" else "📉"


def side_display(side):
    return "LONG" if side == "long" else "SHORT"
