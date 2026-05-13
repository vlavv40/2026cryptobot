import time
import hmac
import hashlib
from urllib.parse import urlencode

import aiohttp
from aiohttp_socks import ProxyConnector

from config import Config
from services.telegram_sender import send_text_to_all
from utils.logger import setup_logger

logger = setup_logger()


class ExecutionService:
    def __init__(self):
        self.base_url = Config.BINANCE_FUTURES_BASE_URL

    def _make_session(self):
        proxy_url = getattr(Config, "PROXY_URL", "")

        if proxy_url:
            connector = ProxyConnector.from_url(proxy_url)
            return aiohttp.ClientSession(connector=connector)

        return aiohttp.ClientSession()

    def _enabled(self) -> bool:
        return bool(
            Config.AUTO_TRADE
            and Config.BINANCE_API_KEY
            and Config.BINANCE_API_SECRET
        )

    def _headers(self) -> dict:
        return {
            "X-MBX-APIKEY": Config.BINANCE_API_KEY
        }

    def _sign(self, params: dict) -> str:
        query = urlencode(params)

        signature = hmac.new(
            Config.BINANCE_API_SECRET.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()

        return f"{query}&signature={signature}"

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
    ):
        params = params or {}

        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000

        signed_query = self._sign(params)

        url = f"{self.base_url}{path}?{signed_query}"

        async with self._make_session() as session:
            async with session.request(
                method,
                url,
                headers=self._headers(),
                timeout=20,
            ) as response:

                data = await response.json()

                if response.status >= 400:
                    raise RuntimeError(
                        f"Binance error {response.status}: {data}"
                    )

                return data

    async def _public_get(
        self,
        path: str,
        params: dict | None = None,
    ):
        url = f"{self.base_url}{path}"

        async with self._make_session() as session:
            async with session.get(
                url,
                params=params or {},
                timeout=20,
            ) as response:

                data = await response.json()

                if response.status >= 400:
                    raise RuntimeError(
                        f"Binance public error {response.status}: {data}"
                    )

                return data

    async def get_price(self, symbol: str) -> float:
        data = await self._public_get(
            "/fapi/v1/ticker/price",
            {"symbol": symbol},
        )

        return float(data["price"])

    async def get_symbol_rules(self, symbol: str) -> dict:
        data = await self._public_get("/fapi/v1/exchangeInfo")

        for item in data.get("symbols", []):

            if item.get("symbol") == symbol:

                step_size = 0.001
                min_qty = 0.0
                tick_size = 0.0001

                for f in item.get("filters", []):

                    if f.get("filterType") == "LOT_SIZE":
                        step_size = float(
                            f.get("stepSize", step_size)
                        )

                        min_qty = float(
                            f.get("minQty", min_qty)
                        )

                    if f.get("filterType") == "PRICE_FILTER":
                        tick_size = float(
                            f.get("tickSize", tick_size)
                        )

                return {
                    "step_size": step_size,
                    "min_qty": min_qty,
                    "tick_size": tick_size,
                }

        return {
            "step_size": 0.001,
            "min_qty": 0.0,
            "tick_size": 0.0001,
        }

    def round_to_step(
        self,
        value: float,
        step: float,
    ) -> float:

        if step <= 0:
            return value

        precision = 0

        text = f"{step:.16f}".rstrip("0")

        if "." in text:
            precision = len(text.split(".")[1])

        rounded = value - (value % step)

        return round(rounded, precision)

    def round_qty(
        self,
        qty: float,
        step_size: float,
    ) -> float:

        return self.round_to_step(qty, step_size)

    def round_price(
        self,
        price: float,
        tick_size: float,
    ) -> float:

        return self.round_to_step(price, tick_size)

    async def get_position_qty(self, symbol: str) -> float:
        data = await self._request(
            "GET",
            "/fapi/v2/positionRisk",
            {
                "symbol": symbol
            },
        )

        if isinstance(data, list):
            for item in data:
                if item.get("symbol") == symbol:
                    return abs(float(item.get("positionAmt", 0)))

        return 0.0

    async def position_exists(self, symbol: str) -> bool:
        qty = await self.get_position_qty(symbol)
        return qty > 0

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
                logger.warning(
                    f"[AUTO TRADE] margin type warning {symbol}: {error}"
                )

        await self._request(
            "POST",
            "/fapi/v1/leverage",
            {
                "symbol": symbol,
                "leverage": Config.AUTO_TRADE_LEVERAGE,
            },
        )

    async def place_market_order(
        self,
        symbol: str,
        direction: str,
        qty: float,
    ):

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

    async def close_position_market(
        self,
        symbol: str,
        direction: str,
    ):
        qty = await self.get_position_qty(symbol)

        if qty <= 0:
            logger.warning(
                f"[AUTO TRADE CLOSE] {symbol} нет открытой позиции для закрытия"
            )
            return None

        rules = await self.get_symbol_rules(symbol)

        qty = self.round_qty(
            qty,
            rules["step_size"],
        )

        if qty <= 0 or qty < rules["min_qty"]:
            logger.warning(
                f"[AUTO TRADE CLOSE] {symbol} некорректный qty для закрытия: {qty}"
            )
            return None

        side = "SELL" if direction == "LONG" else "BUY"

        try:
            await self.cancel_all_algo_orders(symbol)
        except Exception as error:
            logger.warning(
                f"[AUTO TRADE CLOSE] {symbol} не удалось отменить algo orders: {error}"
            )

        result = await self._request(
            "POST",
            "/fapi/v1/order",
            {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": qty,
                "reduceOnly": "true",
            },
        )

        logger.info(
            f"[AUTO TRADE CLOSE] {symbol} {direction} qty={qty}"
        )

        return result

    async def cancel_all_algo_orders(self, symbol: str):
        return await self._request(
            "DELETE",
            "/fapi/v1/algoOpenOrders",
            {
                "symbol": symbol,
            },
        )

    async def place_stop_market(
        self,
        symbol: str,
        direction: str,
        stop_price: float,
    ):

        side = "SELL" if direction == "LONG" else "BUY"

        return await self._request(
            "POST",
            "/fapi/v1/algoOrder",
            {
                "symbol": symbol,
                "side": side,
                "algoType": "CONDITIONAL",
                "type": "STOP_MARKET",
                "triggerPrice": stop_price,
                "closePosition": "true",
                "workingType": "MARK_PRICE",
            },
        )

    async def place_take_profit(
        self,
        symbol: str,
        direction: str,
        trigger_price: float,
        qty: float,
    ):

        side = "SELL" if direction == "LONG" else "BUY"

        return await self._request(
            "POST",
            "/fapi/v1/algoOrder",
            {
                "symbol": symbol,
                "side": side,
                "algoType": "CONDITIONAL",
                "type": "TAKE_PROFIT_MARKET",
                "triggerPrice": trigger_price,
                "quantity": qty,
                "reduceOnly": "true",
                "workingType": "MARK_PRICE",
            },
        )

    async def replace_protection_orders(
        self,
        symbol: str,
        direction: str,
        stop_price: float,
        take_profits: list[tuple[float, float]],
    ):
        rules = await self.get_symbol_rules(symbol)

        stop_price = self.round_price(
            float(stop_price),
            rules["tick_size"],
        )

        await self.cancel_all_algo_orders(symbol)

        await self.place_stop_market(
            symbol,
            direction,
            stop_price,
        )

        for tp_price, qty in take_profits:
            tp_price = self.round_price(
                float(tp_price),
                rules["tick_size"],
            )

            qty = self.round_qty(
                float(qty),
                rules["step_size"],
            )

            if qty > 0:
                await self.place_take_profit(
                    symbol,
                    direction,
                    tp_price,
                    qty,
                )

        logger.info(
            f"[SMART SL] {symbol} {direction} protection replaced | "
            f"stop={stop_price} | tps={take_profits}"
        )

    async def move_stop_after_tp1(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        tp2: float,
        tp3: float,
    ):
        rules = await self.get_symbol_rules(symbol)

        qty = await self.get_position_qty(symbol)

        if qty <= 0:
            logger.warning(
                f"[SMART SL] {symbol} нет позиции после TP1"
            )
            return None

        tp2_qty = self.round_qty(
            qty * 0.67,
            rules["step_size"],
        )

        tp3_qty = self.round_qty(
            qty - tp2_qty,
            rules["step_size"],
        )

        await self.replace_protection_orders(
            symbol=symbol,
            direction=direction,
            stop_price=entry_price,
            take_profits=[
                (tp2, tp2_qty),
                (tp3, tp3_qty),
            ],
        )

        return {
            "qty": qty,
            "new_stop": entry_price,
            "tp2_qty": tp2_qty,
            "tp3_qty": tp3_qty,
        }

    async def move_stop_after_tp2(
        self,
        symbol: str,
        direction: str,
        tp1: float,
        tp3: float,
    ):
        qty = await self.get_position_qty(symbol)

        if qty <= 0:
            logger.warning(
                f"[SMART SL] {symbol} нет позиции после TP2"
            )
            return None

        await self.replace_protection_orders(
            symbol=symbol,
            direction=direction,
            stop_price=tp1,
            take_profits=[
                (tp3, qty),
            ],
        )

        return {
            "qty": qty,
            "new_stop": tp1,
            "tp3_qty": qty,
        }

    async def execute_signal(
        self,
        bot,
        chat_ids: list[str],
        signal,
    ):

        if not self._enabled():
            return None

        symbol = signal.symbol
        direction = signal.direction

        try:

            if Config.AUTO_TRADE_ONE_POSITION_PER_SYMBOL:

                exists = await self.position_exists(symbol)

                if exists:
                    logger.info(
                        f"[AUTO TRADE] {symbol} уже есть позиция"
                    )

                    return None

            await self.set_margin_and_leverage(symbol)

            price = await self.get_price(symbol)

            rules = await self.get_symbol_rules(symbol)

            position_usdt = (
                Config.AUTO_TRADE_USDT
                * Config.AUTO_TRADE_LEVERAGE
            )

            raw_qty = position_usdt / price

            qty = self.round_qty(
                raw_qty,
                rules["step_size"],
            )

            if qty <= 0 or qty < rules["min_qty"]:
                raise RuntimeError(
                    f"Некорректный qty={qty}"
                )

            stop_price = self.round_price(
                float(signal.stop_loss),
                rules["tick_size"],
            )

            tp1 = self.round_price(
                float(signal.tp1),
                rules["tick_size"],
            )

            tp2 = self.round_price(
                float(signal.tp2),
                rules["tick_size"],
            )

            tp3 = self.round_price(
                float(signal.tp3),
                rules["tick_size"],
            )

            entry_order = await self.place_market_order(
                symbol,
                direction,
                qty,
            )

            tp_qty_1 = self.round_qty(
                qty * 0.70,
                rules["step_size"],
            )

            tp_qty_2 = self.round_qty(
                qty * 0.20,
                rules["step_size"],
            )

            tp_qty_3 = self.round_qty(
                qty - tp_qty_1 - tp_qty_2,
                rules["step_size"],
            )

            await self.place_stop_market(
                symbol,
                direction,
                stop_price,
            )

            if tp_qty_1 > 0:
                await self.place_take_profit(
                    symbol,
                    direction,
                    tp1,
                    tp_qty_1,
                )

            if tp_qty_2 > 0:
                await self.place_take_profit(
                    symbol,
                    direction,
                    tp2,
                    tp_qty_2,
                )

            if tp_qty_3 > 0:
                await self.place_take_profit(
                    symbol,
                    direction,
                    tp3,
                    tp_qty_3,
                )

            text = (
                "🚀 <b>AUTO TRADE OPENED</b>\n"
                "━━━━━━━━━━━━━━\n\n"
                f"<b>#{symbol}</b>\n"
                f"Направление: <b>{direction}</b>\n"
                f"Маржа: <b>{Config.AUTO_TRADE_USDT}$</b>\n"
                f"Плечо: <b>x{Config.AUTO_TRADE_LEVERAGE}</b>\n"
                f"Позиция: <b>{position_usdt}$</b>\n"
                f"Qty: <b>{qty}</b>\n\n"
                f"Stop: <code>{stop_price}</code>\n"
                f"TP1: <code>{tp1}</code> — 70%\n"
                f"TP2: <code>{tp2}</code> — 20%\n"
                f"TP3: <code>{tp3}</code> — 10%\n\n"
                "━━━━━━━━━━━━━━"
            )

            await send_text_to_all(
                bot,
                chat_ids,
                text,
            )

            logger.info(
                f"[AUTO TRADE OPENED] {symbol} {direction}"
            )

            return entry_order

        except Exception as error:

            logger.exception(
                f"[AUTO TRADE ERROR] {symbol}: {error}"
            )

            await send_text_to_all(
                bot,
                chat_ids,
                "⚠️ <b>AUTO TRADE ERROR</b>\n\n"
                f"#{symbol}\n"
                f"{direction}\n\n"
                f"<code>{error}</code>",
            )

            return None