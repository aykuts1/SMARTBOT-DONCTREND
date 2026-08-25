import config
import utils


def has_free_slot(state) -> bool:
    return state.open_position_count() < config.MAX_OPEN_POSITIONS


def calc_position_size(balance: float, price: float, qty_step: float, min_qty: float):
    """
    Bakiyenin %10'u marj olarak kullanılır, 25x kaldıraç ile pozisyon büyüklüğü hesaplanır.
    Dönüş: (qty, margin_used, notional) ya da None (min. işlem büyüklüğüne ulaşılamıyorsa).
    """
    margin = balance * config.BALANCE_USAGE_PCT
    notional = margin * config.LEVERAGE
    raw_qty = notional / price

    qty = utils.round_qty_down(raw_qty, qty_step)

    if qty < min_qty or qty <= 0:
        return None

    return qty, margin, qty * price
