import pandas as pd


class BTCFilter:
    def get_bias(self, btc_df: pd.DataFrame) -> str:
        """
        Возвращает направление BTC:
        BULLISH / BEARISH / NEUTRAL
        """
        if btc_df is None or len(btc_df) < 50:
            return "NEUTRAL"

        last = btc_df.iloc[-2]

        ema20 = float(last["ema20"])
        ema50 = float(last["ema50"])
        close = float(last["close"])

        if close > ema20 and ema20 > ema50:
            return "BULLISH"

        if close < ema20 and ema20 < ema50:
            return "BEARISH"

        return "NEUTRAL"

    def allow_trade(self, direction: str, btc_bias: str) -> tuple[bool, str]:
        if btc_bias == "BULLISH" and direction == "SHORT":
            return False, "BTC растёт → шорт запрещён"

        if btc_bias == "BEARISH" and direction == "LONG":
            return False, "BTC падает → лонг запрещён"

        return True, ""