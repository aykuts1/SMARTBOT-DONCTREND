from datetime import datetime, timezone


class BotState:
    """
    Botun çalışırkenki hafızası. Kalıcı değildir (RAM üzerinde tutulur).
    Bot yeniden başladığında (restart/deploy/çökme) bu hafıza sıfırlanır;
    geçmiş açık pozisyonlar bilinmez, sıfırdan başlanır.
    """

    def __init__(self):
        self.open_positions = {}  # symbol -> {side, entry_price, qty, sl_price, opened_at}
        self.cycle_count = 0

    def has_position(self, symbol: str) -> bool:
        return symbol in self.open_positions

    def open_position_count(self) -> int:
        return len(self.open_positions)

    def add_position(self, symbol: str, side: str, entry_price: float, qty: str, sl_price: str):
        self.open_positions[symbol] = {
            "side": side,              # "long" | "short"
            "entry_price": entry_price,
            "qty": qty,
            "sl_price": sl_price,
            "opened_at": datetime.now(timezone.utc),
        }

    def remove_position(self, symbol: str):
        self.open_positions.pop(symbol, None)
