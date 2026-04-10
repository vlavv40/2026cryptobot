import aiohttp
import pandas as pd

from config import Config


class BinanceFuturesClient:
    def __init__(self):
        self.base_url = Config.BINANCE_FUTURES_BASE_URL

    async def get_usdt_futures_symbols(self) -> list[str]:
        url = f"{self.base_url}/fapi/v1/exchangeInfo"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=20) as response:
                data = await response.json()

        symbols = []
        for symbol_info in data.get("symbols", []):
            if (
                symbol_info.get("contractType") == "PERPETUAL"
                and symbol_info.get("quoteAsset") == "USDT"
                and symbol_info.get("status") == "TRADING"
            ):
                symbols.append(symbol_info["symbol"])

        return symbols

    async def get_24h_tickers(self) -> list[dict]:
        url = f"{self.base_url}/fapi/v1/ticker/24hr"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=20) as response:
                data = await response.json()

        if isinstance(data, dict):
            return []
        return data

    async def get_liquid_symbols(self) -> list[str]:
        exchange_symbols = set(await self.get_usdt_futures_symbols())
        tickers = await self.get_24h_tickers()

        valid_priority = []
        for symbol in Config.PRIORITY_SYMBOLS:
            if symbol in exchange_symbols:
                valid_priority.append(symbol)

        if Config.USE_PRIORITY_SYMBOLS_ONLY:
            return valid_priority[: Config.MAX_SYMBOLS_TO_SCAN]

        ticker_map = {}
        for item in tickers:
            symbol = item.get("symbol", "")
            if symbol not in exchange_symbols:
                continue
            if symbol not in Config.PRIORITY_SYMBOLS:
                continue

            try:
                quote_volume = float(item.get("quoteVolume", 0))
                trades_count = int(item.get("count", 0))
            except (TypeError, ValueError):
                continue

            if quote_volume < Config.MIN_24H_QUOTE_VOLUME:
                continue
            if trades_count < Config.MIN_24H_TRADES:
                continue

            ticker_map[symbol] = {
                "quote_volume": quote_volume,
                "trades_count": trades_count,
            }

        result = [
            s for s in Config.PRIORITY_SYMBOLS
            if s in ticker_map
        ]

        return result[: Config.MAX_SYMBOLS_TO_SCAN]

    async def get_klines(self, symbol: str, interval: str, limit: int = 250) -> pd.DataFrame:
        url = f"{self.base_url}/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=20) as response:
                data = await response.json()

        df = pd.DataFrame(
            data,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "trades_count",
                "taker_buy_base",
                "taker_buy_quote",
                "ignore",
            ],
        )

        numeric_columns = [
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_asset_volume",
            "trades_count",
            "taker_buy_base",
            "taker_buy_quote",
        ]

        for col in numeric_columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")

        return df