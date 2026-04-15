from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class SwingPoint:
    index: int
    price: float


@dataclass
class StructureState:
    trend: str  # UP / DOWN / RANGE
    last_high: Optional[float]
    prev_high: Optional[float]
    last_low: Optional[float]
    prev_low: Optional[float]
    strength: float


@dataclass
class SetupDecision:
    valid: bool
    setup_type: str  # TREND_PULLBACK / NONE
    direction: str   # LONG / SHORT / NONE
    reason: str
    zone_low: Optional[float] = None
    zone_high: Optional[float] = None
    invalidation: Optional[float] = None


class StructureEngine:
    def find_swing_highs(self, df: pd.DataFrame, left: int = 3, right: int = 3) -> list[SwingPoint]:
        result: list[SwingPoint] = []

        if len(df) < left + right + 5:
            return result

        for i in range(left, len(df) - right):
            current_high = float(df.iloc[i]["high"])
            left_highs = df.iloc[i - left:i]["high"]
            right_highs = df.iloc[i + 1:i + 1 + right]["high"]

            if current_high >= float(left_highs.max()) and current_high >= float(right_highs.max()):
                result.append(SwingPoint(index=i, price=current_high))

        return result[-10:]

    def find_swing_lows(self, df: pd.DataFrame, left: int = 3, right: int = 3) -> list[SwingPoint]:
        result: list[SwingPoint] = []

        if len(df) < left + right + 5:
            return result

        for i in range(left, len(df) - right):
            current_low = float(df.iloc[i]["low"])
            left_lows = df.iloc[i - left:i]["low"]
            right_lows = df.iloc[i + 1:i + 1 + right]["low"]

            if current_low <= float(left_lows.min()) and current_low <= float(right_lows.min()):
                result.append(SwingPoint(index=i, price=current_low))

        return result[-10:]

    def detect_structure(self, df: pd.DataFrame) -> StructureState:
        highs = self.find_swing_highs(df)
        lows = self.find_swing_lows(df)

        if len(highs) < 2 or len(lows) < 2:
            return StructureState(
                trend="RANGE",
                last_high=None,
                prev_high=None,
                last_low=None,
                prev_low=None,
                strength=0.0,
            )

        prev_high = highs[-2].price
        last_high = highs[-1].price
        prev_low = lows[-2].price
        last_low = lows[-1].price

        uptrend = last_high > prev_high and last_low > prev_low
        downtrend = last_high < prev_high and last_low < prev_low

        if uptrend:
            strength = 1.0
            if (last_high - prev_high) > 0 and (last_low - prev_low) > 0:
                strength += 0.5
            return StructureState(
                trend="UP",
                last_high=last_high,
                prev_high=prev_high,
                last_low=last_low,
                prev_low=prev_low,
                strength=strength,
            )

        if downtrend:
            strength = 1.0
            if (prev_high - last_high) > 0 and (prev_low - last_low) > 0:
                strength += 0.5
            return StructureState(
                trend="DOWN",
                last_high=last_high,
                prev_high=prev_high,
                last_low=last_low,
                prev_low=prev_low,
                strength=strength,
            )

        return StructureState(
            trend="RANGE",
            last_high=last_high,
            prev_high=prev_high,
            last_low=last_low,
            prev_low=prev_low,
            strength=0.5,
        )

    def get_recent_swing_low(self, df: pd.DataFrame) -> Optional[float]:
        lows = self.find_swing_lows(df)
        if not lows:
            return None
        return lows[-1].price

    def get_recent_swing_high(self, df: pd.DataFrame) -> Optional[float]:
        highs = self.find_swing_highs(df)
        if not highs:
            return None
        return highs[-1].price

    def detect_trend_pullback_setup(
        self,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> SetupDecision:
        htf = self.detect_structure(htf_df)
        mtf = self.detect_structure(mtf_df)

        ltf_last = ltf_df.iloc[-2]
        ltf_prev = ltf_df.iloc[-3]

        ema20 = float(ltf_last["ema20"])
        ema50 = float(ltf_last["ema50"])
        close = float(ltf_last["close"])
        prev_close = float(ltf_prev["close"])
        low = float(ltf_last["low"])
        high = float(ltf_last["high"])

        zone_low = min(ema20, ema50)
        zone_high = max(ema20, ema50)

        # LONG
        if htf.trend == "UP" and mtf.trend in ["UP", "RANGE"]:
            in_zone = low <= zone_high and close >= zone_low
            holding_zone = close >= zone_low
            bounce = close >= prev_close or close >= ema20

            invalidation = self.get_recent_swing_low(ltf_df)

            if in_zone and holding_zone and bounce and invalidation is not None:
                return SetupDecision(
                    valid=True,
                    setup_type="TREND_PULLBACK",
                    direction="LONG",
                    reason="восходящая структура + откат в рабочую зону + удержание",
                    zone_low=zone_low,
                    zone_high=zone_high,
                    invalidation=invalidation,
                )

        # SHORT
        if htf.trend == "DOWN" and mtf.trend in ["DOWN", "RANGE"]:
            in_zone = high >= zone_low and close <= zone_high
            holding_zone = close <= zone_high
            bounce = close <= prev_close or close <= ema20

            invalidation = self.get_recent_swing_high(ltf_df)

            if in_zone and holding_zone and bounce and invalidation is not None:
                return SetupDecision(
                    valid=True,
                    setup_type="TREND_PULLBACK",
                    direction="SHORT",
                    reason="нисходящая структура + откат в рабочую зону + удержание",
                    zone_low=zone_low,
                    zone_high=zone_high,
                    invalidation=invalidation,
                )

        return SetupDecision(
            valid=False,
            setup_type="NONE",
            direction="NONE",
            reason="нет качественного pullback-сетапа",
        )

    def detect_setup(
        self,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> SetupDecision:
        return self.detect_trend_pullback_setup(htf_df, mtf_df, ltf_df)