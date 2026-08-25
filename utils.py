def _decimals_from_step(step: float) -> int:
    s = f"{step:.10f}".rstrip("0")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def format_qty(qty: float, qty_step: float) -> str:
    """Miktarı borsanın kabul ettiği adım (qtyStep) büyüklüğüne göre formatlar."""
    if qty_step >= 1:
        return str(int(qty))
    decimals = _decimals_from_step(qty_step)
    return f"{qty:.{decimals}f}"


def round_qty_down(raw_qty: float, qty_step: float) -> float:
    """Miktarı adım büyüklüğüne göre aşağı yuvarlar (borsanın kabul etmediği ondalık hatasını önler)."""
    if qty_step <= 0:
        return raw_qty
    steps = int(raw_qty / qty_step)
    return steps * qty_step


def round_to_tick(price: float, tick_size: float) -> str:
    """Fiyatı borsanın kabul ettiği adım (tickSize) büyüklüğüne göre formatlar."""
    if tick_size <= 0:
        return str(price)
    decimals = _decimals_from_step(tick_size)
    rounded = round(price / tick_size) * tick_size
    return f"{rounded:.{decimals}f}"
