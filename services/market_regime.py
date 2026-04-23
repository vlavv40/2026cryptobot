from dataclasses import dataclass

import pandas as pd

from services.market_structure import MarketStructureAnalyzer


@dataclass
class MarketRegimeReport:
    regime: str  # TREND / RANGE / IMPULSE / OVEREXTENDED / REVERSAL_RISK
    direction: str  # LONG / SHORT / NONE
    is_trending: bool
    is_ranging: bool
    is_impulsive: bool
    is_overextended: bool
    reversal_risk: bool
    reason: str
    score: float


class MarketRegimeAnalyzer:
    def __init__(self):
        self.structure = MarketStructureAnalyzer()

    def _closed(self, df: pd.DataFrame) -> pd.Series:
        return df.iloc[-2]

    def _prev_closed(self, df: pd.DataFrame) -> pd.Series:
        return df.iloc[-3]

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            if pd.isna(value):
                return default
            return float(value)
        except Exception:
            return default

    def detect_regime(self, df: pd.DataFrame) -> MarketRegimeReport:
        if len(df) < 50:
            return MarketRegimeReport(
                regime="RANGE",
                direction="NONE",
                is_trending=False,
                is_ranging=True,
                is_impulsive=False,
                is_overextended=False,
                reversal_risk=False,
                reason="недостаточно данных для определения режима",
                score=0.0,
            )

        structure_report = self.structure.detect_trend(df)

        last = self._closed(df)
        prev = self._prev_closed(df)

        close_price = self._safe_float(last["close"])
        prev_close = self._safe_float(prev["close"])

        ema20 = self._safe_float(last.get("ema20"))
        ema50 = self._safe_float(last.get("ema50"))
        ema200 = self._safe_float(last.get("ema_slow"))
        adx = self._safe_float(last.get("adx"))
        atr = self._safe_float(last.get("atr"))
        atr_ratio = self._safe_float(last.get("atr_ratio"))
        rsi = self._safe_float(last.get("rsi"))
        volume_ratio = self._safe_float(last.get("quote_volume_ratio"), 1.0)

        candle_body = abs(close_price - self._safe_float(last["open"]))
        body_vs_atr = candle_body / atr if atr > 0 else 0.0

        distance_from_ema20 = abs(close_price - ema20) / close_price if close_price > 0 else 0.0
        distance_from_ema50 = abs(close_price - ema50) / close_price if close_price > 0 else 0.0

        bullish_alignment = close_price > ema20 > ema50 > ema200 if ema200 > 0 else False
        bearish_alignment = close_price < ema20 < ema50 < ema200 if ema200 > 0 else False

        almost_bullish_alignment = close_price > ema20 and ema20 > ema50
        almost_bearish_alignment = close_price < ema20 and ema20 < ema50

        is_trending = False
        is_ranging = False
        is_impulsive = False
        is_overextended = False
        reversal_risk = False

        regime = "RANGE"
        direction = "NONE"
        score = 0.0
        reason = "неопределённый режим"

        # 1. Trend detection — мягче
        if (
            structure_report.trend == "UP"
            and (bullish_alignment or almost_bullish_alignment)
            and adx >= 14
        ):
            is_trending = True
            direction = "LONG"
            regime = "TREND"
            score += 2.0
            reason = "восходящий тренд: структура + EMA alignment + ADX"

        elif (
            structure_report.trend == "DOWN"
            and (bearish_alignment or almost_bearish_alignment)
            and adx >= 14
        ):
            is_trending = True
            direction = "SHORT"
            regime = "TREND"
            score += 2.0
            reason = "нисходящий тренд: структура + EMA alignment + ADX"

        # 2. Range detection — немного мягче
        if structure_report.trend == "RANGE" or adx < 12:
            is_ranging = True
            regime = "RANGE"
            direction = "NONE"
            score = max(score, 1.0)
            reason = "боковик: слабая структура или низкий ADX"

        # 3. Impulse detection
        strong_body = body_vs_atr >= 0.85
        strong_atr = atr_ratio >= 0.0035
        strong_volume = volume_ratio >= 1.05
        fast_move_up = close_price > prev_close and rsi >= 53
        fast_move_down = close_price < prev_close and rsi <= 47

        if strong_body and strong_atr and strong_volume:
            if fast_move_up and direction in ["LONG", "NONE"]:
                is_impulsive = True
                regime = "IMPULSE"
                direction = "LONG"
                score = max(score, 3.0)
                reason = "сильный бычий импульс: тело свечи + ATR expansion + объём"

            elif fast_move_down and direction in ["SHORT", "NONE"]:
                is_impulsive = True
                regime = "IMPULSE"
                direction = "SHORT"
                score = max(score, 3.0)
                reason = "сильный медвежий импульс: тело свечи + ATR expansion + объём"

        # 4. Overextended detection — чуть мягче к рынку
        too_far_from_mean = distance_from_ema20 >= 0.016 or distance_from_ema50 >= 0.026

        if direction == "LONG":
            if rsi >= 69 and too_far_from_mean:
                is_overextended = True
                regime = "OVEREXTENDED"
                score = max(score, 3.2)
                reason = "рынок перегрет вверх: RSI высокий и цена далеко от EMA"

        elif direction == "SHORT":
            if rsi <= 31 and too_far_from_mean:
                is_overextended = True
                regime = "OVEREXTENDED"
                score = max(score, 3.2)
                reason = "рынок перегрет вниз: RSI низкий и цена далеко от EMA"

        # 5. Reversal risk — не так агрессивно
        if structure_report.choch == "BEARISH" and (rsi >= 62 or close_price < ema20):
            reversal_risk = True
            regime = "REVERSAL_RISK"
            direction = "SHORT"
            score = max(score, 3.5)
            reason = "риск разворота вниз: bearish CHOCH + ослабление цены"

        elif structure_report.choch == "BULLISH" and (rsi <= 38 or close_price > ema20):
            reversal_risk = True
            regime = "REVERSAL_RISK"
            direction = "LONG"
            score = max(score, 3.5)
            reason = "риск разворота вверх: bullish CHOCH + усиление цены"

        return MarketRegimeReport(
            regime=regime,
            direction=direction,
            is_trending=is_trending,
            is_ranging=is_ranging,
            is_impulsive=is_impulsive,
            is_overextended=is_overextended,
            reversal_risk=reversal_risk,
            reason=reason,
            score=round(score, 2),
        )