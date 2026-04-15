from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str  # HIGH / LOW


@dataclass
class StructureReport:
    trend: str  # UP / DOWN / RANGE
    last_high: Optional[float]
    prev_high: Optional[float]
    last_low: Optional[float]
    prev_low: Optional[float]
    hh: bool
    hl: bool
    lh: bool
    ll: bool
    bos: str  # BULLISH / BEARISH / NONE
    choch: str  # BULLISH / BEARISH / NONE
    strength: float


class MarketStructureAnalyzer:
    def __init__(self, swing_left: int = 3, swing_right: int = 3):
        self.swing_left = swing_left
        self.swing_right = swing_right

    def find_swing_highs(self, df: pd.DataFrame) -> list[SwingPoint]:
        swings: list[SwingPoint] = []

        if len(df) < self.swing_left + self.swing_right + 5:
            return swings

        for i in range(self.swing_left, len(df) - self.swing_right):
            current_high = float(df.iloc[i]["high"])

            left_highs = df.iloc[i - self.swing_left:i]["high"]
            right_highs = df.iloc[i + 1:i + 1 + self.swing_right]["high"]

            if current_high >= float(left_highs.max()) and current_high >= float(right_highs.max()):
                swings.append(SwingPoint(index=i, price=current_high, kind="HIGH"))

        return swings[-20:]

    def find_swing_lows(self, df: pd.DataFrame) -> list[SwingPoint]:
        swings: list[SwingPoint] = []

        if len(df) < self.swing_left + self.swing_right + 5:
            return swings

        for i in range(self.swing_left, len(df) - self.swing_right):
            current_low = float(df.iloc[i]["low"])

            left_lows = df.iloc[i - self.swing_left:i]["low"]
            right_lows = df.iloc[i + 1:i + 1 + self.swing_right]["low"]

            if current_low <= float(left_lows.min()) and current_low <= float(right_lows.min()):
                swings.append(SwingPoint(index=i, price=current_low, kind="LOW"))

        return swings[-20:]

    def get_last_two_highs(self, df: pd.DataFrame) -> tuple[Optional[SwingPoint], Optional[SwingPoint]]:
        highs = self.find_swing_highs(df)
        if len(highs) < 2:
            return None, None
        return highs[-1], highs[-2]

    def get_last_two_lows(self, df: pd.DataFrame) -> tuple[Optional[SwingPoint], Optional[SwingPoint]]:
        lows = self.find_swing_lows(df)
        if len(lows) < 2:
            return None, None
        return lows[-1], lows[-2]

    def detect_trend(self, df: pd.DataFrame) -> StructureReport:
        last_high, prev_high = self.get_last_two_highs(df)
        last_low, prev_low = self.get_last_two_lows(df)

        if not last_high or not prev_high or not last_low or not prev_low:
            return StructureReport(
                trend="RANGE",
                last_high=None,
                prev_high=None,
                last_low=None,
                prev_low=None,
                hh=False,
                hl=False,
                lh=False,
                ll=False,
                bos="NONE",
                choch="NONE",
                strength=0.0,
            )

        hh = last_high.price > prev_high.price
        hl = last_low.price > prev_low.price
        lh = last_high.price < prev_high.price
        ll = last_low.price < prev_low.price

        trend = "RANGE"
        strength = 0.5

        if hh and hl:
            trend = "UP"
            strength = 1.0

        elif lh and ll:
            trend = "DOWN"
            strength = 1.0

        close_price = float(df.iloc[-2]["close"])

        bos = "NONE"
        choch = "NONE"

        # BOS = пробой последнего ключевого свинга по направлению структуры
        if trend == "UP" and close_price > last_high.price:
            bos = "BULLISH"

        elif trend == "DOWN" and close_price < last_low.price:
            bos = "BEARISH"

        # CHOCH = слом структуры против основного направления
        if trend == "UP" and close_price < last_low.price:
            choch = "BEARISH"

        elif trend == "DOWN" and close_price > last_high.price:
            choch = "BULLISH"

        # Усиливаем score структуры
        if trend == "UP":
            up_range = (last_high.price - prev_high.price) + (last_low.price - prev_low.price)
            if up_range > 0:
                strength += 0.5

        elif trend == "DOWN":
            down_range = (prev_high.price - last_high.price) + (prev_low.price - last_low.price)
            if down_range > 0:
                strength += 0.5

        return StructureReport(
            trend=trend,
            last_high=last_high.price,
            prev_high=prev_high.price,
            last_low=last_low.price,
            prev_low=prev_low.price,
            hh=hh,
            hl=hl,
            lh=lh,
            ll=ll,
            bos=bos,
            choch=choch,
            strength=round(strength, 2),
        )

    def get_recent_swing_high(self, df: pd.DataFrame) -> Optional[float]:
        highs = self.find_swing_highs(df)
        if not highs:
            return None
        return highs[-1].price

    def get_recent_swing_low(self, df: pd.DataFrame) -> Optional[float]:
        lows = self.find_swing_lows(df)
        if not lows:
            return None
        return lows[-1].price

    def is_bullish_structure(self, df: pd.DataFrame) -> bool:
        report = self.detect_trend(df)
        return report.trend == "UP"

    def is_bearish_structure(self, df: pd.DataFrame) -> bool:
        report = self.detect_trend(df)
        return report.trend == "DOWN"

    def is_range_structure(self, df: pd.DataFrame) -> bool:
        report = self.detect_trend(df)
        return report.trend == "RANGE"