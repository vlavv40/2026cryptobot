from dataclasses import dataclass
from typing import Optional

import pandas as pd

from config import Config


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
    setup_type: str  # PULLBACK_CONTINUATION / BREAKOUT_RETEST / MOMENTUM_CONTINUATION / NONE
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
        ltf_prev = ltf_df.iloc[-3]

        close_ = float(ltf_last["close"])
        ema20 = float(ltf_last["ema20"])
        ema50 = float(ltf_last["ema50"])
        prev_close = float(ltf_prev["close"])

        # LONG
        if htf_structure.trend == "UP":
            pullback_ok = (
                close_ >= ema20
                or close_ >= ema50
                or (close_ >= ema20 * 0.995)
            )

            momentum_hint = close_ >= prev_close

            if mtf_structure.trend in ["UP", "RANGE"] and pullback_ok and momentum_hint:
                return SetupContext(
                    setup_type="PULLBACK_CONTINUATION",
                    direction="LONG",
                    reason="восходящая структура + мягкий откат без слома тренда",
                )

        # SHORT
        if htf_structure.trend == "DOWN":
            pullback_ok = (
                close_ <= ema20
                or close_ <= ema50
                or (close_ <= ema20 * 1.005)
            )

            momentum_hint = close_ <= prev_close

            if mtf_structure.trend in ["DOWN", "RANGE"] and pullback_ok and momentum_hint:
                return SetupContext(
                    setup_type="PULLBACK_CONTINUATION",
                    direction="SHORT",
                    reason="нисходящая структура + мягкий откат без слома тренда",
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

        ltf_close = float(ltf_last["close"])
        ltf_low = float(ltf_last["low"])
        ltf_high = float(ltf_last["high"])
        prev_close = float(ltf_prev["close"])

        tolerance_up = range_high * 0.0025
        tolerance_down = range_low * 0.0025

        broke_up = float(mtf_last["close"]) > range_high
        retest_up = ltf_low <= (range_high + tolerance_up) and ltf_close >= (range_high - tolerance_up)
        strength_up = ltf_close >= prev_close

        if broke_up and retest_up and strength_up:
            return SetupContext(
                setup_type="BREAKOUT_RETEST",
                direction="LONG",
                reason="пробой диапазона вверх + мягкий ретест уровня",
            )

        broke_down = float(mtf_last["close"]) < range_low
        retest_down = ltf_high >= (range_low - tolerance_down) and ltf_close <= (range_low + tolerance_down)
        strength_down = ltf_close <= prev_close

        if broke_down and retest_down and strength_down:
            return SetupContext(
                setup_type="BREAKOUT_RETEST",
                direction="SHORT",
                reason="пробой диапазона вниз + мягкий ретест уровня",
            )

        return SetupContext(
            setup_type="NONE",
            direction="NONE",
            reason="breakout retest не найден",
        )

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            if pd.isna(value):
                return default
            return float(value)
        except Exception:
            return default

    def _indicator_trend(self, row: pd.Series, min_adx: float) -> str:
        close = self._safe_float(row.get("close"))
        ema20 = self._safe_float(row.get("ema20"))
        ema50 = self._safe_float(row.get("ema50"))
        ema_fast = self._safe_float(row.get("ema_fast"))
        ema_slow = self._safe_float(row.get("ema_slow"))
        adx = self._safe_float(row.get("adx"))

        if close <= 0 or ema20 <= 0 or ema50 <= 0:
            return "NONE"

        bullish_ema = close > ema20 and ema20 >= ema50
        bearish_ema = close < ema20 and ema20 <= ema50

        if ema_fast > 0 and ema_slow > 0:
            bullish_ema = bullish_ema or (close > ema20 and ema_fast > ema_slow)
            bearish_ema = bearish_ema or (close < ema20 and ema_fast < ema_slow)

        if adx < min_adx:
            return "NONE"

        if bullish_ema:
            return "LONG"

        if bearish_ema:
            return "SHORT"

        return "NONE"

    def _soft_indicator_trend(self, row: pd.Series, min_adx: float) -> str:
        close = self._safe_float(row.get("close"))
        ema20 = self._safe_float(row.get("ema20"))
        ema50 = self._safe_float(row.get("ema50"))
        ema_fast = self._safe_float(row.get("ema_fast"))
        ema_slow = self._safe_float(row.get("ema_slow"))
        adx = self._safe_float(row.get("adx"))
        rsi = self._safe_float(row.get("rsi"))
        macd_hist = self._safe_float(row.get("macd_hist"))

        if close <= 0 or ema20 <= 0 or ema50 <= 0:
            return "NONE"

        if adx < max(min_adx - 4.0, 10.0):
            return "NONE"

        bullish_bias = (
            (close > ema20 and ema20 >= ema50 * 0.997)
            or (close > ema50 and ema_fast > ema_slow)
            or (rsi >= 52 and macd_hist >= 0 and close >= ema20 * 0.995)
        )
        bearish_bias = (
            (close < ema20 and ema20 <= ema50 * 1.003)
            or (close < ema50 and ema_fast < ema_slow)
            or (rsi <= 48 and macd_hist <= 0 and close <= ema20 * 1.005)
        )

        if bullish_bias and not bearish_bias:
            return "LONG"

        if bearish_bias and not bullish_bias:
            return "SHORT"

        return "NONE"

    def _direction_score(self, row: pd.Series, direction: str, min_adx: float) -> float:
        close = self._safe_float(row.get("close"))
        ema20 = self._safe_float(row.get("ema20"))
        ema50 = self._safe_float(row.get("ema50"))
        ema_fast = self._safe_float(row.get("ema_fast"))
        ema_slow = self._safe_float(row.get("ema_slow"))
        adx = self._safe_float(row.get("adx"))
        rsi = self._safe_float(row.get("rsi"), 50.0)
        macd_hist = self._safe_float(row.get("macd_hist"))

        if close <= 0 or ema20 <= 0 or ema50 <= 0:
            return 0.0

        score = 0.0

        if adx >= min_adx:
            score += 1.0
        elif adx >= max(min_adx - 4.0, 10.0):
            score += 0.5

        if direction == "LONG":
            if close >= ema20:
                score += 0.7
            if close >= ema50:
                score += 0.5
            if ema20 >= ema50:
                score += 0.5
            if ema_fast > ema_slow:
                score += 0.4
            if macd_hist >= 0:
                score += 0.5
            if rsi >= 50:
                score += 0.4
        else:
            if close <= ema20:
                score += 0.7
            if close <= ema50:
                score += 0.5
            if ema20 <= ema50:
                score += 0.5
            if ema_fast < ema_slow:
                score += 0.4
            if macd_hist <= 0:
                score += 0.5
            if rsi <= 50:
                score += 0.4

        return score

    def detect_adaptive_continuation(
        self,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> SetupContext:
        if len(htf_df) < 60 or len(mtf_df) < 60 or len(ltf_df) < 10:
            return SetupContext("NONE", "NONE", "недостаточно данных для adaptive continuation")

        htf_last = htf_df.iloc[-2]
        mtf_last = mtf_df.iloc[-2]
        ltf_last = ltf_df.iloc[-2]
        ltf_prev = ltf_df.iloc[-3]

        close = self._safe_float(ltf_last.get("close"))
        prev_close = self._safe_float(ltf_prev.get("close"))
        macd_hist = self._safe_float(ltf_last.get("macd_hist"))
        prev_macd_hist = self._safe_float(ltf_prev.get("macd_hist"))
        rsi = self._safe_float(ltf_last.get("rsi"), 50.0)
        atr_ratio = self._safe_float(ltf_last.get("atr_ratio"))
        adx = self._safe_float(ltf_last.get("adx"))
        volume_ratio = self._safe_float(ltf_last.get("quote_volume_ratio"), 1.0)

        if volume_ratio < Config.MIN_SETUP_VOLUME_RATIO:
            return SetupContext("NONE", "NONE", "adaptive continuation: слабый 15m volume")

        if atr_ratio < Config.MIN_SETUP_ATR_RATIO and adx < 22:
            return SetupContext("NONE", "NONE", "adaptive continuation: слабый 15m ATR")

        long_score = (
            self._direction_score(htf_last, "LONG", Config.MIN_ADX_4H) * 1.1
            + self._direction_score(mtf_last, "LONG", Config.MIN_ADX_1H)
            + self._direction_score(ltf_last, "LONG", max(Config.MIN_ADX_1H - 2, 10))
        )
        short_score = (
            self._direction_score(htf_last, "SHORT", Config.MIN_ADX_4H) * 1.1
            + self._direction_score(mtf_last, "SHORT", Config.MIN_ADX_1H)
            + self._direction_score(ltf_last, "SHORT", max(Config.MIN_ADX_1H - 2, 10))
        )

        long_momentum = (
            (close > prev_close or macd_hist > prev_macd_hist)
            and 42 <= rsi <= Config.LONG_MAX_RSI_ENTRY
        )
        short_momentum = (
            (close < prev_close or macd_hist < prev_macd_hist)
            and Config.SHORT_MIN_RSI_ENTRY <= rsi <= 58
        )

        if long_score >= 6.1 and long_score >= short_score + 0.9 and long_momentum:
            return SetupContext(
                setup_type="MOMENTUM_CONTINUATION",
                direction="LONG",
                reason="адаптивный trend/momentum continuation: EMA/ADX/MACD согласованы",
            )

        if short_score >= 6.1 and short_score >= long_score + 0.9 and short_momentum:
            return SetupContext(
                setup_type="MOMENTUM_CONTINUATION",
                direction="SHORT",
                reason="адаптивный trend/momentum continuation: EMA/ADX/MACD согласованы",
            )

        return SetupContext(
            setup_type="NONE",
            direction="NONE",
            reason="adaptive continuation не найден",
        )

    def detect_momentum_continuation(
        self,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> SetupContext:
        if len(htf_df) < 60 or len(mtf_df) < 60 or len(ltf_df) < 10:
            return SetupContext("NONE", "NONE", "недостаточно данных для momentum continuation")

        htf_last = htf_df.iloc[-2]
        mtf_last = mtf_df.iloc[-2]
        ltf_last = ltf_df.iloc[-2]
        ltf_prev = ltf_df.iloc[-3]

        htf_dir = self._soft_indicator_trend(htf_last, Config.MIN_ADX_4H)
        mtf_dir = self._soft_indicator_trend(mtf_last, Config.MIN_ADX_1H)

        close = self._safe_float(ltf_last.get("close"))
        prev_close = self._safe_float(ltf_prev.get("close"))
        ema20 = self._safe_float(ltf_last.get("ema20"))
        ema50 = self._safe_float(ltf_last.get("ema50"))
        macd_hist = self._safe_float(ltf_last.get("macd_hist"))
        prev_macd_hist = self._safe_float(ltf_prev.get("macd_hist"))
        rsi = self._safe_float(ltf_last.get("rsi"), 50.0)
        atr_ratio = self._safe_float(ltf_last.get("atr_ratio"))
        adx = self._safe_float(ltf_last.get("adx"))
        volume_ratio = self._safe_float(ltf_last.get("quote_volume_ratio"), 1.0)
        min_volume_ratio = min(Config.MIN_CONFIRMATION_VOLUME_RATIO, Config.MIN_SETUP_VOLUME_RATIO)
        min_atr_ratio = min(Config.MIN_ATR_RATIO_15M, Config.MIN_SETUP_ATR_RATIO)
        atr_ok = atr_ratio >= min_atr_ratio or adx >= 22

        if htf_dir == "LONG" and mtf_dir in {"LONG", "NONE"}:
            ltf_aligned = close >= min(ema20, ema50) * 0.998
            momentum_ok = close > prev_close or macd_hist > prev_macd_hist
            rsi_ok = 42 <= rsi <= Config.LONG_MAX_RSI_ENTRY
            volume_ok = volume_ratio >= min_volume_ratio

            if ltf_aligned and momentum_ok and rsi_ok and volume_ok and atr_ok:
                return SetupContext(
                    setup_type="MOMENTUM_CONTINUATION",
                    direction="LONG",
                    reason="тренд по EMA/ADX + рабочее продолжение импульса на 15m",
                )

        if htf_dir == "SHORT" and mtf_dir in {"SHORT", "NONE"}:
            ltf_aligned = close <= max(ema20, ema50) * 1.002
            momentum_ok = close < prev_close or macd_hist < prev_macd_hist
            rsi_ok = Config.SHORT_MIN_RSI_ENTRY <= rsi <= 58
            volume_ok = volume_ratio >= min_volume_ratio

            if ltf_aligned and momentum_ok and rsi_ok and volume_ok and atr_ok:
                return SetupContext(
                    setup_type="MOMENTUM_CONTINUATION",
                    direction="SHORT",
                    reason="тренд по EMA/ADX + рабочее продолжение импульса на 15m",
                )

        return SetupContext(
            setup_type="NONE",
            direction="NONE",
            reason="momentum continuation не найден",
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

        momentum = self.detect_momentum_continuation(htf_df, mtf_df, ltf_df)
        if momentum.setup_type != "NONE":
            return momentum

        adaptive = self.detect_adaptive_continuation(htf_df, mtf_df, ltf_df)
        if adaptive.setup_type != "NONE":
            return adaptive

        return SetupContext(
            setup_type="NONE",
            direction="NONE",
            reason="структурный сетап не найден",
        )
