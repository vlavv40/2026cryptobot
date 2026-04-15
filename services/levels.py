from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass
class LevelsReport:
    range_high: Optional[float]
    range_low: Optional[float]
    nearest_resistance: Optional[float]
    nearest_support: Optional[float]
    in_middle_of_range: bool
    range_size_pct: float
    support_gap_pct: Optional[float]
    resistance_gap_pct: Optional[float]
    retest_zone_low: Optional[float]
    retest_zone_high: Optional[float]
    reason: str


class LevelsAnalyzer:
    def __init__(self, lookback: int = 50):
        self.lookback = lookback

    def _closed(self, df: pd.DataFrame) -> pd.Series:
        return df.iloc[-2]

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            if pd.isna(value):
                return default
            return float(value)
        except Exception:
            return default

    def get_range_high_low(self, df: pd.DataFrame, bars: int = 40) -> tuple[Optional[float], Optional[float]]:
        if len(df) < bars + 2:
            return None, None

        recent = df.iloc[-bars-2:-2]
        range_high = self._safe_float(recent["high"].max(), None)
        range_low = self._safe_float(recent["low"].min(), None)

        return range_high, range_low

    def find_local_resistance(self, df: pd.DataFrame, current_price: float, bars: int = 80) -> Optional[float]:
        if len(df) < bars + 2:
            return None

        recent = df.iloc[-bars-2:-2]
        highs = sorted(set(round(float(x), 6) for x in recent["high"].tolist()))

        candidates = [h for h in highs if h > current_price]
        if not candidates:
            return None

        return min(candidates)

    def find_local_support(self, df: pd.DataFrame, current_price: float, bars: int = 80) -> Optional[float]:
        if len(df) < bars + 2:
            return None

        recent = df.iloc[-bars-2:-2]
        lows = sorted(set(round(float(x), 6) for x in recent["low"].tolist()))

        candidates = [l for l in lows if l < current_price]
        if not candidates:
            return None

        return max(candidates)

    def calculate_gaps(
        self,
        current_price: float,
        support: Optional[float],
        resistance: Optional[float],
    ) -> tuple[Optional[float], Optional[float]]:
        support_gap_pct = None
        resistance_gap_pct = None

        if support is not None and current_price > 0:
            support_gap_pct = (current_price - support) / current_price

        if resistance is not None and current_price > 0:
            resistance_gap_pct = (resistance - current_price) / current_price

        return support_gap_pct, resistance_gap_pct

    def detect_middle_of_range(
        self,
        current_price: float,
        range_low: Optional[float],
        range_high: Optional[float],
    ) -> bool:
        if range_low is None or range_high is None:
            return False

        if range_high <= range_low:
            return False

        range_size = range_high - range_low
        lower_middle = range_low + range_size * 0.35
        upper_middle = range_low + range_size * 0.65

        return lower_middle <= current_price <= upper_middle

    def build_retest_zone(
        self,
        level: Optional[float],
        atr: float,
        side: str,
    ) -> tuple[Optional[float], Optional[float]]:
        if level is None or atr <= 0:
            return None, None

        zone_size = atr * 0.35

        if side == "LONG":
            return level - zone_size, level + zone_size

        if side == "SHORT":
            return level - zone_size, level + zone_size

        return None, None

    def analyze(self, df: pd.DataFrame, side: str = "NONE") -> LevelsReport:
        if len(df) < 60:
            return LevelsReport(
                range_high=None,
                range_low=None,
                nearest_resistance=None,
                nearest_support=None,
                in_middle_of_range=False,
                range_size_pct=0.0,
                support_gap_pct=None,
                resistance_gap_pct=None,
                retest_zone_low=None,
                retest_zone_high=None,
                reason="недостаточно данных для уровней",
            )

        last = self._closed(df)
        current_price = self._safe_float(last["close"])
        atr = self._safe_float(last.get("atr"), 0.0)

        range_high, range_low = self.get_range_high_low(df, bars=40)
        resistance = self.find_local_resistance(df, current_price, bars=80)
        support = self.find_local_support(df, current_price, bars=80)

        support_gap_pct, resistance_gap_pct = self.calculate_gaps(
            current_price=current_price,
            support=support,
            resistance=resistance,
        )

        in_middle = self.detect_middle_of_range(
            current_price=current_price,
            range_low=range_low,
            range_high=range_high,
        )

        range_size_pct = 0.0
        if range_high is not None and range_low is not None and current_price > 0:
            range_size_pct = (range_high - range_low) / current_price

        retest_zone_low = None
        retest_zone_high = None

        if side == "LONG":
            retest_zone_low, retest_zone_high = self.build_retest_zone(
                level=support,
                atr=atr,
                side="LONG",
            )
        elif side == "SHORT":
            retest_zone_low, retest_zone_high = self.build_retest_zone(
                level=resistance,
                atr=atr,
                side="SHORT",
            )

        reason = "уровни определены"
        if in_middle:
            reason = "цена в середине диапазона"
        elif resistance_gap_pct is not None and resistance_gap_pct < 0.008:
            reason = "слишком близкое сопротивление"
        elif support_gap_pct is not None and support_gap_pct < 0.008:
            reason = "слишком близкая поддержка"

        return LevelsReport(
            range_high=range_high,
            range_low=range_low,
            nearest_resistance=resistance,
            nearest_support=support,
            in_middle_of_range=in_middle,
            range_size_pct=round(range_size_pct, 6),
            support_gap_pct=round(support_gap_pct, 6) if support_gap_pct is not None else None,
            resistance_gap_pct=round(resistance_gap_pct, 6) if resistance_gap_pct is not None else None,
            retest_zone_low=round(retest_zone_low, 6) if retest_zone_low is not None else None,
            retest_zone_high=round(retest_zone_high, 6) if retest_zone_high is not None else None,
            reason=reason,
        )