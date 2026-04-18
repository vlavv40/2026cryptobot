from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class MarketStructure:
    trend: str  # UP / DOWN / RANGE
    last_swing_high: Optional[float]
    last_swing_low: Optional[float]
    prev_swing_high: Optional[float]
    prev_swing_low: Optional[float]
    structure_strength: float


@dataclass
class SetupContext:
    setup_type: str  # PULLBACK_CONTINUATION / BREAKOUT_RETEST / NONE
    direction: str   # LONG / SHORT / NONE
    reason: str


class StructureEngine:
    def find_swings(self, df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        highs = []
        lows = []

        if len(df) < left + right + 5:
            return highs, lows

        for i in range(left, len(df) - right):
            current_high = float(df.iloc[i]["high"])
            current_low = float(df.iloc[i]["low"])

            left_highs = df.iloc[i - left:i]["high"]
            right_highs = df.iloc[i + 1:i + 1 + right]["high"]

            left_lows = df.iloc[i - left:i]["low"]
            right_lows = df.iloc[i + 1:i + 1 + right]["low"]

            if current_high >= left_highs.max() and current_high >= right_highs.max():
                highs.append((i, current_high))

            if current_low <= left_lows.min() and current_low <= right_lows.min():
                lows.append((i, current_low))

        return highs[-10:], lows[-10:]

    def detect_market_structure(self, df: pd.DataFrame) -> MarketStructure:
        swing_highs, swing_lows = self.find_swings(df)

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return MarketStructure(
                trend="RANGE",
                last_swing_high=None,
                last_swing_low=None,
                prev_swing_high=None,
                prev_swing_low=None,
                structure_strength=0.0,
            )

        prev_swing_high = swing_highs[-2][1]
        last_swing_high = swing_highs[-1][1]
        prev_swing_low = swing_lows[-2][1]
        last_swing_low = swing_lows[-1][1]

        uptrend = last_swing_high > prev_swing_high and last_swing_low > prev_swing_low
        downtrend = last_swing_high < prev_swing_high and last_swing_low < prev_swing_low

        if uptrend:
            strength = 1.0
            if (last_swing_high - prev_swing_high) > 0 and (last_swing_low - prev_swing_low) > 0:
                strength += 0.5
            return MarketStructure(
                trend="UP",
                last_swing_high=last_swing_high,
                last_swing_low=last_swing_low,
                prev_swing_high=prev_swing_high,
                prev_swing_low=prev_swing_low,
                structure_strength=strength,
            )

        if downtrend:
            strength = 1.0
            if (prev_swing_high - last_swing_high) > 0 and (prev_swing_low - last_swing_low) > 0:
                strength += 0.5
            return MarketStructure(
                trend="DOWN",
                last_swing_high=last_swing_high,
                last_swing_low=last_swing_low,
                prev_swing_high=prev_swing_high,
                prev_swing_low=prev_swing_low,
                structure_strength=strength,
            )

        return MarketStructure(
            trend="RANGE",
            last_swing_high=last_swing_high,
            last_swing_low=last_swing_low,
            prev_swing_high=prev_swing_high,
            prev_swing_low=prev_swing_low,
            structure_strength=0.5,
        )

    def detect_pullback_continuation(
        self,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> SetupContext:
        htf_structure = self.detect_market_structure(htf_df)
        mtf_structure = self.detect_market_structure(mtf_df)

        ltf_last = ltf_df.iloc[-2]

        if htf_structure.trend == "UP":
            pullback_ok = (
                ltf_last["close"] >= ltf_last["ema20"]
                or ltf_last["close"] >= ltf_last["ema50"]
            )
            if mtf_structure.trend in ["UP", "RANGE"] and pullback_ok:
                return SetupContext(
                    setup_type="PULLBACK_CONTINUATION",
                    direction="LONG",
                    reason="восходящая структура + откат без слома тренда",
                )

        if htf_structure.trend == "DOWN":
            pullback_ok = (
                ltf_last["close"] <= ltf_last["ema20"]
                or ltf_last["close"] <= ltf_last["ema50"]
            )
            if mtf_structure.trend in ["DOWN", "RANGE"] and pullback_ok:
                return SetupContext(
                    setup_type="PULLBACK_CONTINUATION",
                    direction="SHORT",
                    reason="нисходящая структура + откат без слома тренда",
                )

        return SetupContext(
            setup_type="NONE",
            direction="NONE",
            reason="pullback continuation не найден",
        )

    def detect_breakout_retest(
        self,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> SetupContext:
        if len(mtf_df) < 30 or len(ltf_df) < 30:
            return SetupContext("NONE", "NONE", "недостаточно данных для breakout/retest")

        mtf_last = mtf_df.iloc[-2]
        recent = mtf_df.iloc[-25:-2]

        range_high = float(recent["high"].max())
        range_low = float(recent["low"].min())

        ltf_last = ltf_df.iloc[-2]
        ltf_prev = ltf_df.iloc[-3]

        broke_up = float(mtf_last["close"]) > range_high
        retest_up = float(ltf_last["low"]) <= range_high and float(ltf_last["close"]) >= range_high
        strength_up = float(ltf_last["close"]) > float(ltf_prev["close"])

        if broke_up and retest_up and strength_up:
            return SetupContext(
                setup_type="BREAKOUT_RETEST",
                direction="LONG",
                reason="пробой диапазона вверх + ретест уровня",
            )

        broke_down = float(mtf_last["close"]) < range_low
        retest_down = float(ltf_last["high"]) >= range_low and float(ltf_last["close"]) <= range_low
        strength_down = float(ltf_last["close"]) < float(ltf_prev["close"])

        if broke_down and retest_down and strength_down:
            return SetupContext(
                setup_type="BREAKOUT_RETEST",
                direction="SHORT",
                reason="пробой диапазона вниз + ретест уровня",
            )

        return SetupContext(
            setup_type="NONE",
            direction="NONE",
            reason="breakout retest не найден",
        )

    def detect_setup(
        self,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> SetupContext:
        pullback = self.detect_pullback_continuation(htf_df, mtf_df, ltf_df)
        if pullback.setup_type != "NONE":
            return pullback

        breakout = self.detect_breakout_retest(mtf_df, ltf_df)
        if breakout.setup_type != "NONE":
            return breakout

        return SetupContext(
            setup_type="NONE",
            direction="NONE",
            reason="структурный сетап не найден",
        )