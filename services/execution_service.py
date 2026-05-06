import time
import hmac
import hashlib
from urllib.parse import urlencode

import aiohttp

from config import Config
from services.telegram_sender import send_text_to_all
from utils.logger import setup_logger

logger = setup_logger()


class ExecutionService:
    def __init__(self):
        self.base_url = Config.BINANCE_FUTURES_BASE_URL

    def _enabled(self) -> bool:
        return bool(Config.AUTO_TRADE and Config.BINANCE_API_KEY and Config.BINANCE_API_SECRET)

    def _headers(self) -> dict:
        return {"X-MBX-APIKEY": Config.BINANCE_API_KEY}

    def _sign(self, params: dict) -> str:
        query = urlencode(params)
        signature = hmac.new(
            Config.BINANCE_API_SECRET.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={signature}"

    async def _request(self, method: str, path: str, params: dict | None = None):
        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000

        signed_query = self._sign(params)
        url = f"{self.base_url}{path}?{signed_query}"

        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, headers=self._headers(), timeout=20) as response:
                data = await response.json()

                if response.status >= 400:
                    raise RuntimeError(f"Binance error {response.status}: {data}")

                return data

    async def _public_get(self, path: str, params: dict | None = None):
        url = f"{self.base_url}{path}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params or {}, timeout=20) as response:
                data = await response.json()

                if response.status >= 400:
                    raise RuntimeError(f"Binance public error {response.status}: {data}")

                return data

    async def get_price(self, symbol: str) -> float:
        data = await self._public_get("/fapi/v1/ticker/price", {"symbol": symbol})
        return float(data["price"])

    async def get_symbol_rules(self, symbol: str) -> dict:
        data = await self._public_get("/fapi/v1/exchangeInfo")

        for item in data.get("symbols", []):
            if item.get("symbol") == symbol:
                step_size = 0.001
                min_qty = 0.0

                for f in item.get("filters", []):
                    if f.get("filterType") == "LOT_SIZE":
                        step_size = float(f.get("stepSize", step_size))
                        min_qty = float(f.get("minQty", min_qty))

                return {
                    "step_size": step_size,
                    "min_qty": min_qty,
                }

        return {"step_size": 0.001, "min_qty": 0.0}

    def round_qty(self, qty: float, step_size: float) -> float:
        if step_size <= 0:
            return qty

        precision = 0
        text = f"{step_size:.16f}".rstrip("0")

        if "." in text:
            precision = len(text.split(".")[1])

        rounded = qty - (qty % step_size)
        return round(rounded, precision)

    async def position_exists(self, symbol: str) -> bool:
        data = await self._request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})

        if isinstance(data, list):
            for item in data:
                if item.get("symbol") == symbol and abs(float(item.get("positionAmt", 0))) > 0:
                    return True

        return False

    async def set_margin_and_leverage(self, symbol: str):
        try:
            await self._request(
                "POST",
                "/fapi/v1/marginType",
                {
                    "symbol": symbol,
                    "marginType": Config.AUTO_TRADE_MARGIN_TYPE,
                },
            )
        except Exception as error:
            text = str(error)
            if "No need to change margin type" not in text:
                logger.warning(f"[AUTO TRADE] margin type warning {symbol}: {error}")

        await self._request(
            "POST",
            "/fapi/v1/leverage",
            {
                "symbol": symbol,
                "leverage": Config.AUTO_TRADE_LEVERAGE,
            },
        )

    async def place_market_order(self, symbol: str, direction: str, qty: float):
        side = "BUY" if direction == "LONG" else "SELL"

        return await self._request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": qty,
            },
        )

    async def place_stop_market(self, symbol: str, direction: str, stop_price: float):
        side = "SELL" if direction == "LONG" else "BUY"

        return await self._request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "STOP_MARKET",
                "stopPrice": stop_price,
                "closePosition": "true",
                "workingType": "MARK_PRICE",
            },
        )

    async def place_take_profit(self, symbol: str, direction: str, stop_price: float, qty: float):
        side = "SELL" if direction == "LONG" else "BUY"

        return await self._request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": stop_price,
                "quantity": qty,
                "reduceOnly": "true",
                "workingType": "MARK_PRICE",
            },
        )

    async def execute_signal(self, bot, chat_ids: list[str], signal):
        if not self._enabled():
            return None

        symbol = signal.symbol
        direction = signal.direction

        try:
            if Config.AUTO_TRADE_ONE_POSITION_PER_SYMBOL:
                exists = await self.position_exists(symbol)
                if exists:
                    logger.info(f"[AUTO TRADE] {symbol} уже есть позиция, пропускаю")
                    return None

            await self.set_margin_and_leverage(symbol)

            price = await self.get_price(symbol)
            rules = await self.get_symbol_rules(symbol)

            position_usdt = Config.AUTO_TRADE_USDT * Config.AUTO_TRADE_LEVERAGE
            raw_qty = position_usdt / price
            qty = self.round_qty(raw_qty, rules["step_size"])

            if qty <= 0 or qty < rules["min_qty"]:
                raise RuntimeError(f"Некорректный qty={qty}, min_qty={rules['min_qty']}")

            entry_order = await self.place_market_order(symbol, direction, qty)

            tp_qty_1 = self.round_qty(qty * 0.34, rules["step_size"])
            tp_qty_2 = self.round_qty(qty * 0.33, rules["step_size"])
            tp_qty_3 = self.round_qty(qty - tp_qty_1 - tp_qty_2, rules["step_size"])

            await self.place_stop_market(symbol, direction, signal.stop_loss)

            if tp_qty_1 > 0:
                await self.place_take_profit(symbol, direction, signal.tp1, tp_qty_1)
            if tp_qty_2 > 0:
                await self.place_take_profit(symbol, direction, signal.tp2, tp_qty_2)
            if tp_qty_3 > 0:
                await self.place_take_profit(symbol, direction, signal.tp3, tp_qty_3)

            text = (
                "🚀 <b>AUTO TRADE OPENED</b>\n"
                "━━━━━━━━━━━━━━\n\n"
                f"<b>#{symbol}</b>\n"
                f"Направление: <b>{direction}</b>\n"
                f"Маржа: <b>{Config.AUTO_TRADE_USDT}$</b>\n"
                f"Плечо: <b>x{Config.AUTO_TRADE_LEVERAGE}</b>\n"
                f"Позиция: <b>{position_usdt}$</b>\n"
                f"Qty: <b>{qty}</b>\n\n"
                f"Stop: <code>{signal.stop_loss}</code>\n"
                f"TP1: <code>{signal.tp1}</code>\n"
                f"TP2: <code>{signal.tp2}</code>\n"
                f"TP3: <code>{signal.tp3}</code>\n\n"
                "━━━━━━━━━━━━━━"
            )

            await send_text_to_all(bot, chat_ids, text)
            logger.info(f"[AUTO TRADE OPENED] {symbol} {direction} qty={qty}")

            return entry_order

        except Exception as error:
            logger.exception(f"[AUTO TRADE ERROR] {symbol} {direction}: {error}")

            await send_text_to_all(
                bot,
                chat_ids,
                "⚠️ <b>AUTO TRADE ERROR</b>\n\n"
                f"#{symbol}\n"
                f"{direction}\n\n"
                f"<code>{error}</code>",
            )

            return None