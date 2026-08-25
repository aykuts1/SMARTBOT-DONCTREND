import time

import pandas as pd
from pybit.unified_trading import HTTP

import config


class BybitClient:
    """
    Veri Toplama İstasyonu + Emir Gönderme İstasyonu.
    Bybit Futures (linear/USDT perpetual) ile tüm iletişim buradan geçer.
    Gerçek hesap kullanılır, testnet YOKTUR.
    """

    def __init__(self):
        self.session = HTTP(
            api_key=config.BYBIT_API_KEY,
            api_secret=config.BYBIT_API_SECRET,
            testnet=False,
        )
        self._leverage_set = set()

    # ---------- Kurulum ----------

    def ensure_cross_margin(self):
        """Hesabı Cross Margin moduna alır (Unified Trading Account, hesap geneli)."""
        try:
            self.session.set_margin_mode(setMarginMode="REGULAR_MARGIN")
            print("[BİLGİ] Margin modu: Cross (REGULAR_MARGIN) olarak ayarlandı.")
        except Exception as e:
            print(f"[BİLGİ] Margin modu ayarlanamadı ya da zaten Cross: {e}")

    def ensure_leverage(self, symbol: str):
        """İlgili sembol için kaldıracı ayarlar (her sembol için sadece bir kez dener)."""
        if symbol in self._leverage_set:
            return
        try:
            self.session.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(config.LEVERAGE),
                sellLeverage=str(config.LEVERAGE),
            )
        except Exception as e:
            print(f"[BİLGİ] {symbol} kaldıraç ayarlanamadı ya da zaten {config.LEVERAGE}x: {e}")
        self._leverage_set.add(symbol)

    # ---------- Veri okuma ----------

    def get_klines(self, symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
        """
        Belirtilen zaman diliminde mum verisi çeker.
        Henüz kapanmamış (oluşmakta olan) mum varsa listeden atılır.
        """
        resp = self.session.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=limit,
        )
        rows = resp["result"]["list"]
        rows = rows[::-1]  # Bybit en yeniden en eskiye döner; biz eskiden yeniye çeviriyoruz

        df = pd.DataFrame(rows, columns=["start", "open", "high", "low", "close", "volume", "turnover"])
        for col in ["open", "high", "low", "close", "volume", "turnover"]:
            df[col] = df[col].astype(float)
        df["start"] = df["start"].astype(int)

        interval_ms = int(interval) * 60 * 1000
        now_ms = int(time.time() * 1000)
        df = df[df["start"] + interval_ms <= now_ms].reset_index(drop=True)
        return df

    def get_available_balance(self) -> float:
        """UNIFIED hesabın toplam kullanılabilir bakiyesini (USDT) döndürür."""
        resp = self.session.get_wallet_balance(accountType="UNIFIED")
        acct = resp["result"]["list"][0]
        return float(acct["totalAvailableBalance"])

    def get_instrument_info(self, symbol: str) -> dict:
        resp = self.session.get_instruments_info(category="linear", symbol=symbol)
        item = resp["result"]["list"][0]
        lot = item["lotSizeFilter"]
        price_filter = item["priceFilter"]
        return {
            "qty_step": float(lot["qtyStep"]),
            "min_qty": float(lot["minOrderQty"]),
            "tick_size": float(price_filter["tickSize"]),
        }

    def get_open_position_size(self, symbol: str) -> float:
        """Borsadaki gerçek pozisyon büyüklüğünü döndürür (reconcile için)."""
        resp = self.session.get_positions(category="linear", symbol=symbol)
        positions = resp["result"]["list"]
        total = 0.0
        for p in positions:
            total += float(p.get("size", 0) or 0)
        return total

    # ---------- Emir gönderme ----------

    def place_market_order(self, symbol: str, side: str, qty: str, stop_loss: str = None):
        """side: 'Buy' | 'Sell'"""
        params = dict(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=qty,
            positionIdx=0,
        )
        if stop_loss:
            params["stopLoss"] = stop_loss
        return self.session.place_order(**params)

    def close_position_market(self, symbol: str, position_side: str, qty: str):
        """
        Açık pozisyonu kapatır. position_side pozisyonun YÖNÜDÜR ('Buy'/'Sell'),
        gönderilecek kapatma emri bunun tersi olur.
        """
        close_side = "Sell" if position_side == "Buy" else "Buy"
        return self.session.place_order(
            category="linear",
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty=qty,
            reduceOnly=True,
            positionIdx=0,
        )
