import os
import time
from pybit.unified_trading import HTTP
from logger_setup import get_logger
from utils import tick_round, qty_round_down, qty_to_str, price_to_str, sl_round

log = get_logger("bybit_client")


class BybitClient:
    def __init__(self):
        self.api_key = os.environ.get("BYBIT_API_KEY", "")
        self.api_secret = os.environ.get("BYBIT_API_SECRET", "")
        self.testnet = os.environ.get("BYBIT_TESTNET", "false").lower() == "true"

        self.client = HTTP(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet
        )
        self.instrument_info = {}
        # Bakiye cache (rate limit koruması)
        self._balance_cache = None
        self._balance_cache_time = 0
        self._balance_cache_ttl = 1.0  # 1 saniye
        self._balance_lock = __import__("threading").Lock()
        log.info("Bybit REST client baslatildi (testnet=%s)", self.testnet)

    def test_connection(self):
        try:
            result = self.client.get_server_time()
            if result["retCode"] == 0:
                log.info("Bybit baglantisi basarili")
                return True
            else:
                log.error("Bybit baglanti hatasi: %s", result["retMsg"])
                return False
        except Exception as e:
            log.error("Bybit baglanti hatasi: %s", e)
            return False

    def get_balance(self, force_refresh=False):
        # Cache kontrolü (1 saniye TTL)
        with self._balance_lock:
            if (not force_refresh and self._balance_cache and
                    (time.time() - self._balance_cache_time) < self._balance_cache_ttl):
                return dict(self._balance_cache)

        try:
            result = self.client.get_wallet_balance(accountType="UNIFIED")
            if result["retCode"] == 0:
                top_avail = result["result"]["list"][0].get("totalAvailableBalance", "")
                coins = result["result"]["list"][0]["coin"]
                for coin in coins:
                    if coin["coin"] == "USDT":
                        wallet_balance_raw = coin.get("walletBalance", "")
                        avail_raw = coin.get("availableToWithdraw", "")

                        balance = float(wallet_balance_raw) if wallet_balance_raw else 0.0

                        if avail_raw:
                            available = float(avail_raw)
                        elif top_avail:
                            available = float(top_avail)
                        else:
                            available = balance

                        log.info("Bakiye: %.2f USDT, Serbest: %.2f USDT", balance, available)
                        result_data = {
                            "total": balance,
                            "available": available,
                            "used": max(0.0, balance - available)
                        }
                        with self._balance_lock:
                            self._balance_cache = result_data
                            self._balance_cache_time = time.time()
                        return dict(result_data)
            log.error("Bakiye alinamadi: %s", result.get("retMsg", ""))
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
                    tick_size = float(item["priceFilter"]["tickSize"])
                    min_qty = float(item["lotSizeFilter"]["minOrderQty"])
                    qty_step = float(item["lotSizeFilter"]["qtyStep"])
                    self.instrument_info[symbol] = {
                        "tick_size": tick_size,
                        "min_qty": min_qty,
                        "qty_step": qty_step
                    }
                    log.debug("%s: tick=%.8f min_qty=%.8f step=%.8f",
                              symbol, tick_size, min_qty, qty_step)
                else:
                    log.warning("%s: Instrument bilgisi alinamadi: %s",
                                symbol, result.get("retMsg", ""))
                time.sleep(0.1)
            except Exception as e:
                log.error("%s instrument hatasi: %s", symbol, e)
        log.info("Instrument bilgisi yuklendi: %d / %d coin",
                 len(self.instrument_info), len(symbols))

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
        log.info("Hesap ayarlari uygulaniyor (%d coin, %dx kaldirac)...", len(symbols), leverage)
        for i, symbol in enumerate(symbols):
            try:
                try:
                    self.client.switch_position_mode(
                        category="linear", symbol=symbol, mode=3
                    )
                    log.debug("%s: Hedge modu ayarlandi", symbol)
                except Exception:
                    log.debug("%s: Hedge modu zaten aktif", symbol)
                time.sleep(0.15)

                try:
                    self.client.switch_margin_mode(
                        category="linear", symbol=symbol, tradeMode=0,
                        buyLeverage=str(leverage), sellLeverage=str(leverage)
                    )
                    log.debug("%s: Cross marjin ayarlandi", symbol)
                except Exception:
                    log.debug("%s: Cross marjin zaten aktif", symbol)
                time.sleep(0.15)

                try:
                    self.client.set_leverage(
                        category="linear", symbol=symbol,
                        buyLeverage=str(leverage), sellLeverage=str(leverage)
                    )
                    log.debug("%s: Kaldirac %dx ayarlandi", symbol, leverage)
                except Exception:
                    log.debug("%s: Kaldirac zaten %dx", symbol, leverage)
                time.sleep(0.15)

            except Exception as e:
                log.warning("%s: Hesap ayar hatasi: %s", symbol, e)

        log.info("Hesap ayarlari tamamlandi")

    def get_klines(self, symbol, interval="30", limit=200):
        try:
            result = self.client.get_kline(
                category="linear", symbol=symbol,
                interval=interval, limit=limit
            )
            if result["retCode"] == 0:
                candles = []
                for c in reversed(result["result"]["list"]):
                    candles.append({
                        "timestamp": int(c[0]),
                        "open": float(c[1]),
                        "high": float(c[2]),
                        "low": float(c[3]),
                        "close": float(c[4]),
                        "volume": float(c[5])
                    })
                return candles
            else:
                log.error("%s kline hatasi: %s", symbol, result.get("retMsg", ""))
                return []
        except Exception as e:
            log.error("%s kline hatasi: %s", symbol, e)
            return []

    def get_positions(self):
        try:
            result = self.client.get_positions(
                category="linear", settleCoin="USDT"
            )
            if result["retCode"] == 0:
                positions = []
                for pos in result["result"]["list"]:
                    size = float(pos["size"])
                    if size > 0:
                        positions.append({
                            "symbol": pos["symbol"],
                            "side": "long" if pos["side"] == "Buy" else "short",
                            "size": size,
                            "entry_price": float(pos["avgPrice"]),
                            "unrealised_pnl": float(pos["unrealisedPnl"]),
                            "position_idx": int(pos["positionIdx"]),
                            "order_link_id": pos.get("orderLinkId", ""),
                            "stop_loss": float(pos["stopLoss"]) if pos["stopLoss"] != "" else 0,
                            "leverage": float(pos["leverage"])
                        })
                return positions
            else:
                log.error("Pozisyon hatasi: %s", result.get("retMsg", ""))
                return []
        except Exception as e:
            log.error("Pozisyon hatasi: %s", e)
            return []

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

    def place_order(self, symbol, side, qty, sl_price=None, order_link_id=None):
        try:
            bybit_side = "Buy" if side == "long" else "Sell"
            position_idx = 1 if side == "long" else 2

            info = self.instrument_info.get(symbol, {})
            tick_size = info.get("tick_size", 0.01)
            qty_step = info.get("qty_step", 0.001)

            rounded_qty = qty_round_down(qty, qty_step)

            params = {
                "category": "linear",
                "symbol": symbol,
                "side": bybit_side,
                "orderType": "Market",
                "qty": qty_to_str(rounded_qty, qty_step),
                "positionIdx": position_idx,
                "timeInForce": "IOC"
            }

            if order_link_id:
                params["orderLinkId"] = order_link_id

            log.info("Emir gonderiliyor: %s %s %s qty=%.6f",
                     symbol, side, bybit_side, rounded_qty)

            result = self.client.place_order(**params)

            if result["retCode"] == 0:
                order_id = result["result"]["orderId"]
                log.info("Emir basarili: %s %s %s orderId=%s",
                         symbol, side, rounded_qty, order_id)
                return {
                    "success": True,
                    "order_id": order_id,
                    "qty": rounded_qty
                }
            else:
                log.error("Emir hatasi: %s - %s", symbol, result["retMsg"])
                return {
                    "success": False,
                    "error": result["retMsg"]
                }

        except Exception as e:
            log.error("Emir hatasi: %s - %s", symbol, e)
            return {
                "success": False,
                "error": str(e)
            }

    def set_position_sl(self, symbol, side, sl_price):
        try:
            position_idx = 1 if side == "long" else 2
            info = self.instrument_info.get(symbol, {})
            tick_size = info.get("tick_size", 0.01)
            rounded_sl = sl_round(0, sl_price, tick_size, side)
            result = self.client.set_trading_stop(
                category="linear",
                symbol=symbol,
                stopLoss=price_to_str(rounded_sl, tick_size),
                slTriggerBy="LastPrice",
                positionIdx=position_idx
            )
            if result["retCode"] == 0:
                log.info("Pozisyon SL guncellendi: %s %s → %.6f", symbol, side, rounded_sl)
                return True
            else:
                log.error("Pozisyon SL guncellenemedi: %s %s hata=%s", symbol, side, result.get("retMsg", ""))
                return False
        except Exception as e:
            log.error("Pozisyon SL guncelleme hatasi: %s %s %s", symbol, side, e)
            return False

    def close_position(self, symbol, side, qty):
        close_side = "Sell" if side == "long" else "Buy"
        position_idx = 1 if side == "long" else 2

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
                positionIdx=position_idx,
                reduceOnly=True,
                timeInForce="IOC"
            )

            if result["retCode"] == 0:
                order_id = result["result"]["orderId"]
                log.info("Pozisyon kapatildi: %s %s qty=%s", symbol, side, rounded_qty)
                return {
                    "success": True,
                    "order_id": order_id,
                    "qty": rounded_qty
                }
            elif result["retCode"] == 110017:
                log.warning("Kapatma: %s %s pozisyon zaten kapali (110017), internal state temizleniyor", symbol, side)
                return {
                    "success": True,
                    "already_closed": True,
                    "order_id": "",
                    "qty": rounded_qty
                }
            else:
                log.error("Kapatma hatasi: %s %s - %s", symbol, side, result["retMsg"])
                return {
                    "success": False,
                    "error": result["retMsg"]
                }
        except Exception as e:
            if "110017" in str(e):
                log.warning("Kapatma: %s %s pozisyon zaten kapali (110017)", symbol, side)
                return {"success": True, "already_closed": True, "order_id": "", "qty": rounded_qty}
            log.error("Kapatma hatasi: %s %s - %s", symbol, side, e)
            return {
                "success": False,
                "error": str(e)
            }

    def cancel_all_orders(self, symbol):
        try:
            result = self.client.cancel_all_orders(
                category="linear", symbol=symbol
            )
            return result["retCode"] == 0
        except Exception as e:
            log.error("Emir iptal hatasi: %s - %s", symbol, e)
            return False
