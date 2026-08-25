import os
import time
import threading
from pybit.unified_trading import HTTP
from logger_setup import get_logger
from utils import qty_round_down, qty_to_str, price_to_str, sl_round

log = get_logger("bybit_client")


class BybitClient:
    """Spec §1: Bybit Futures MAINNET, testnet kullanilmiyor. Tek yonlu
    (one-way) pozisyon modu - bot ayni coinde ayni anda tek yon tutar."""

    def __init__(self):
        api_key = os.environ.get("BYBIT_API_KEY", "")
        api_secret = os.environ.get("BYBIT_API_SECRET", "")

        self.client = HTTP(api_key=api_key, api_secret=api_secret)
        self.instrument_info = {}

        self._balance_cache = None
        self._balance_cache_time = 0
        self._balance_cache_ttl = 1.0
        self._balance_lock = threading.Lock()

        log.info("Bybit REST client baslatildi (mainnet)")

    def test_connection(self):
        try:
            result = self.client.get_server_time()
            if result["retCode"] == 0:
                log.info("Bybit baglantisi basarili")
                return True
            log.error("Bybit baglanti hatasi: %s", result["retMsg"])
            return False
        except Exception as e:
            log.error("Bybit baglanti hatasi: %s", e)
            return False

    def get_balance(self, force_refresh=False):
        with self._balance_lock:
            if (not force_refresh and self._balance_cache and
                    (time.time() - self._balance_cache_time) < self._balance_cache_ttl):
                return dict(self._balance_cache)

        try:
            result = self.client.get_wallet_balance(accountType="UNIFIED")
            if result["retCode"] != 0:
                log.error("Bakiye alinamadi: %s", result.get("retMsg", ""))
                return None

            acc = result["result"]["list"][0]
            top_avail = acc.get("totalAvailableBalance", "")
            for coin in acc["coin"]:
                if coin["coin"] != "USDT":
                    continue
                balance = float(coin.get("walletBalance") or 0.0)
                avail_raw = coin.get("availableToWithdraw", "")
                available = float(avail_raw) if avail_raw else (float(top_avail) if top_avail else balance)

                data = {"total": balance, "available": available, "used": max(0.0, balance - available)}
                with self._balance_lock:
                    self._balance_cache = data
                    self._balance_cache_time = time.time()
                log.info("Bakiye: %.2f USDT, Serbest: %.2f USDT", balance, available)
                return dict(data)
            return None
        except Exception as e:
            log.error("Bakiye hatasi: %s", e)
            return None

    def load_instrument_info(self, symbols):
        log.info("Instrument bilgisi yukleniyor: %d coin...", len(symbols))
        for symbol in symbols:
            try:
                result = self.client.get_instruments_info(category="linear", symbol=symbol)
                if result["retCode"] == 0 and result["result"]["list"]:
                    item = result["result"]["list"][0]
                    self.instrument_info[symbol] = {
                        "tick_size": float(item["priceFilter"]["tickSize"]),
                        "min_qty": float(item["lotSizeFilter"]["minOrderQty"]),
                        "qty_step": float(item["lotSizeFilter"]["qtyStep"]),
                    }
                else:
                    log.warning("%s: Instrument bilgisi alinamadi: %s", symbol, result.get("retMsg", ""))
                time.sleep(0.1)
            except Exception as e:
                log.error("%s instrument hatasi: %s", symbol, e)
        log.info("Instrument bilgisi yuklendi: %d / %d coin", len(self.instrument_info), len(symbols))

    def get_tick_size(self, symbol):
        info = self.instrument_info.get(symbol)
        return info["tick_size"] if info else 0.01

    def get_min_qty(self, symbol):
        info = self.instrument_info.get(symbol)
        return info["min_qty"] if info else 0.001

    def get_qty_step(self, symbol):
        info = self.instrument_info.get(symbol)
        return info["qty_step"] if info else 0.001

    def setup_account(self, symbols, leverage):
        """Spec §1: Cross marjin, sabit kaldirac. Tek yonlu pozisyon modu -
        bot ayni coinde ayni anda sadece bir yon tasidigi icin hedge moduna
        gerek yok."""
        log.info("Hesap ayarlari uygulaniyor (%d coin, %dx kaldirac, cross marjin)...", len(symbols), leverage)
        for symbol in symbols:
            try:
                try:
                    self.client.switch_position_mode(category="linear", symbol=symbol, mode=0)
                except Exception:
                    pass
                time.sleep(0.15)

                try:
                    self.client.switch_margin_mode(
                        category="linear", symbol=symbol, tradeMode=0,
                        buyLeverage=str(leverage), sellLeverage=str(leverage)
                    )
                except Exception:
                    pass
                time.sleep(0.15)

                try:
                    self.client.set_leverage(
                        category="linear", symbol=symbol,
                        buyLeverage=str(leverage), sellLeverage=str(leverage)
                    )
                except Exception:
                    pass
                time.sleep(0.15)
            except Exception as e:
                log.warning("%s: Hesap ayar hatasi: %s", symbol, e)
        log.info("Hesap ayarlari tamamlandi")

    def get_klines(self, symbol, interval, limit=200):
        try:
            result = self.client.get_kline(category="linear", symbol=symbol, interval=interval, limit=limit)
            if result["retCode"] != 0:
                log.error("%s kline hatasi: %s", symbol, result.get("retMsg", ""))
                return []
            candles = []
            for c in reversed(result["result"]["list"]):
                candles.append({
                    "timestamp": int(c[0]),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": float(c[5]),
                })
            return candles
        except Exception as e:
            log.error("%s kline hatasi: %s", symbol, e)
            return []

    def get_positions(self):
        try:
            result = self.client.get_positions(category="linear", settleCoin="USDT")
            if result["retCode"] != 0:
                log.error("Pozisyon hatasi: %s", result.get("retMsg", ""))
                return []
            positions = []
            for pos in result["result"]["list"]:
                size = float(pos["size"])
                if size <= 0:
                    continue
                positions.append({
                    "symbol": pos["symbol"],
                    "side": "long" if pos["side"] == "Buy" else "short",
                    "size": size,
                    "entry_price": float(pos["avgPrice"]),
                    "unrealised_pnl": float(pos["unrealisedPnl"]),
                    "stop_loss": float(pos["stopLoss"]) if pos["stopLoss"] != "" else 0,
                })
            return positions
        except Exception as e:
            log.error("Pozisyon hatasi: %s", e)
            return []

    def get_position_size(self, symbol, side):
        for pos in self.get_positions():
            if pos["symbol"] == symbol and pos["side"] == side:
                return pos["size"]
        return 0.0

    def get_closed_pnl(self, symbol=None, limit=100):
        try:
            params = {"category": "linear", "limit": limit}
            if symbol:
                params["symbol"] = symbol
            result = self.client.get_closed_pnl(**params)
            if result["retCode"] == 0:
                return result["result"]["list"]
            return []
        except Exception as e:
            log.error("Kapanmis PnL hatasi: %s", e)
            return []

    def place_order(self, symbol, side, qty, order_link_id=None):
        try:
            bybit_side = "Buy" if side == "long" else "Sell"
            info = self.instrument_info.get(symbol, {})
            qty_step = info.get("qty_step", 0.001)
            rounded_qty = qty_round_down(qty, qty_step)

            params = {
                "category": "linear",
                "symbol": symbol,
                "side": bybit_side,
                "orderType": "Market",
                "qty": qty_to_str(rounded_qty, qty_step),
                "positionIdx": 0,
                "timeInForce": "IOC",
            }
            if order_link_id:
                params["orderLinkId"] = order_link_id

            log.info("Emir gonderiliyor: %s %s qty=%.6f", symbol, bybit_side, rounded_qty)
            result = self.client.place_order(**params)

            if result["retCode"] == 0:
                order_id = result["result"]["orderId"]
                log.info("Emir basarili: %s %s qty=%.6f orderId=%s", symbol, side, rounded_qty, order_id)
                return {"success": True, "order_id": order_id, "qty": rounded_qty}
            log.error("Emir hatasi: %s - %s", symbol, result["retMsg"])
            return {"success": False, "error": result["retMsg"]}
        except Exception as e:
            log.error("Emir hatasi: %s - %s", symbol, e)
            return {"success": False, "error": str(e)}

    def set_position_sl(self, symbol, side, sl_price):
        try:
            tick_size = self.get_tick_size(symbol)
            rounded_sl = sl_round(sl_price, tick_size, side)
            result = self.client.set_trading_stop(
                category="linear",
                symbol=symbol,
                stopLoss=price_to_str(rounded_sl, tick_size),
                slTriggerBy="LastPrice",
                positionIdx=0,
            )
            if result["retCode"] == 0:
                log.info("Pozisyon SL guncellendi: %s %s -> %.6f", symbol, side, rounded_sl)
                return True
            log.error("Pozisyon SL guncellenemedi: %s %s hata=%s", symbol, side, result.get("retMsg", ""))
            return False
        except Exception as e:
            log.error("Pozisyon SL guncelleme hatasi: %s %s %s", symbol, side, e)
            return False

    def close_position(self, symbol, side, qty):
        close_side = "Sell" if side == "long" else "Buy"
        info = self.instrument_info.get(symbol, {})
        qty_step = info.get("qty_step", 0.001)
        rounded_qty = qty_round_down(qty, qty_step)

        try:
            result = self.client.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=qty_to_str(rounded_qty, qty_step),
                positionIdx=0,
                reduceOnly=True,
                timeInForce="IOC",
            )
            if result["retCode"] == 0:
                log.info("Pozisyon kapatildi: %s %s qty=%s", symbol, side, rounded_qty)
                return {"success": True, "order_id": result["result"]["orderId"], "qty": rounded_qty}
            if result["retCode"] == 110017:
                log.warning("Kapatma: %s %s pozisyon zaten kapali (110017)", symbol, side)
                return {"success": True, "already_closed": True, "order_id": "", "qty": rounded_qty}
            log.error("Kapatma hatasi: %s %s - %s", symbol, side, result["retMsg"])
            return {"success": False, "error": result["retMsg"]}
        except Exception as e:
            if "110017" in str(e):
                log.warning("Kapatma: %s %s pozisyon zaten kapali (110017)", symbol, side)
                return {"success": True, "already_closed": True, "order_id": "", "qty": rounded_qty}
            log.error("Kapatma hatasi: %s %s - %s", symbol, side, e)
            return {"success": False, "error": str(e)}
