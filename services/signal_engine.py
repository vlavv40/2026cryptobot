from dataclasses import dataclass
from typing import Optional

import pandas as pd

from config import Config
from services.indicators import (
    add_adx,
    add_atr,
    add_ema,
    add_macd,
    add_rsi,
    add_support_resistance,
    atr_ratio,
)
from services.levels import LevelsAnalyzer
from services.market_regime import MarketRegimeAnalyzer
from services.market_structure import MarketStructureAnalyzer
from services.risk_manager import RiskManager


@dataclass
class Signal:
    symbol: str
    direction: str
    entry_min: float
    entry_max: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    score: float
    reasons: list[str]
    diagnostics: dict
    signal_type: str


@dataclass
class SignalCheckResult:
    symbol: str
    signal: Optional[Signal]
    skip_reason: str
    diagnostics: dict


class SignalEngine:
    def __init__(self):
        self.structure = MarketStructureAnalyzer()
        self.regime = MarketRegimeAnalyzer()
        self.levels = LevelsAnalyzer()
        self.risk = RiskManager()

    def prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        df["ema20"] = add_ema(df, Config.EMA_ENTRY_FAST)
        df["ema50"] = add_ema(df, Config.EMA_ENTRY_SLOW)
        df["ema_fast"] = add_ema(df, Config.EMA_FAST)
        df["ema_slow"] = add_ema(df, Config.EMA_SLOW)

        df["rsi"] = add_rsi(df, Config.RSI_PERIOD)
        df["macd"], df["macd_signal"], df["macd_hist"] = add_macd(df)
        df["atr"] = add_atr(df, Config.ATR_PERIOD)
        df["adx"] = add_adx(df, Config.ADX_PERIOD)
        df["atr_ratio"] = atr_ratio(df, Config.ATR_PERIOD)
        df["support"], df["resistance"] = add_support_resistance(df, 30, 2)

        df["quote_volume_avg_20"] = df["quote_asset_volume"].rolling(window=20).mean()
        df["quote_volume_ratio"] = df["quote_asset_volume"] / df["quote_volume_avg_20"]

        return df

    def _closed(self, df: pd.DataFrame) -> pd.Series:
        return df.iloc[-2]

    def _prev_closed(self, df: pd.DataFrame) -> pd.Series:
        return df.iloc[-3]

    def _build_diagnostics(
        self,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
        structure_htf,
        structure_mtf,
        regime_mtf,
        levels_mtf,
    ) -> dict:
        htf_last = self._closed(htf_df)
        mtf_last = self._closed(mtf_df)
        ltf_last = self._closed(ltf_df)

        return {
            "htf_adx": round(float(htf_last["adx"]), 3) if pd.notna(htf_last["adx"]) else None,
            "mtf_adx": round(float(mtf_last["adx"]), 3) if pd.notna(mtf_last["adx"]) else None,
            "ltf_rsi": round(float(ltf_last["rsi"]), 3) if pd.notna(ltf_last["rsi"]) else None,
            "ltf_macd_hist": round(float(ltf_last["macd_hist"]), 6) if pd.notna(ltf_last["macd_hist"]) else None,
            "ltf_atr_ratio": round(float(ltf_last["atr_ratio"]), 6) if pd.notna(ltf_last["atr_ratio"]) else None,
            "ltf_quote_volume_ratio": round(float(ltf_last["quote_volume_ratio"]), 3) if pd.notna(ltf_last["quote_volume_ratio"]) else None,
            "htf_trend": structure_htf.trend,
            "mtf_trend": structure_mtf.trend,
            "mtf_regime": regime_mtf.regime,
            "mtf_regime_direction": regime_mtf.direction,
            "range_high": levels_mtf.range_high,
            "range_low": levels_mtf.range_low,
            "nearest_resistance": levels_mtf.nearest_resistance,
            "nearest_support": levels_mtf.nearest_support,
            "resistance_gap": levels_mtf.resistance_gap_pct,
            "support_gap": levels_mtf.support_gap_pct,
            "in_middle_of_range": levels_mtf.in_middle_of_range,
        }

    def _detect_direction(self, structure_htf, regime_mtf) -> str:
        if structure_htf.trend == "UP" and regime_mtf.direction == "LONG":
            return "LONG"
        if structure_htf.trend == "DOWN" and regime_mtf.direction == "SHORT":
            return "SHORT"
        return "NONE"

    def _check_context(
        self,
        structure_htf,
        structure_mtf,
        regime_mtf,
        levels_mtf,
    ) -> tuple[bool, str]:
        if structure_htf.trend == "RANGE":
            return False, "нет тренда на HTF"

        if regime_mtf.is_ranging:
            return False, "рынок во флэте на MTF"

        if regime_mtf.is_overextended:
            return False, "рынок перегрет, вход поздний"

        if regime_mtf.reversal_risk:
            return False, "есть риск разворота"

        if levels_mtf.in_middle_of_range:
            return False, "цена в середине диапазона"

        if structure_htf.trend == "UP" and structure_mtf.trend == "DOWN":
            return False, "MTF ломает бычий контекст HTF"

        if structure_htf.trend == "DOWN" and structure_mtf.trend == "UP":
            return False, "MTF ломает медвежий контекст HTF"

        return True, ""

    def _check_pullback_entry(
        self,
        direction: str,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
        levels_mtf,
    ) -> tuple[bool, str, float]:
        mtf_last = self._closed(mtf_df)
        ltf_last = self._closed(ltf_df)
        ltf_prev = self._prev_closed(ltf_df)

        mtf_ema20 = float(mtf_last["ema20"])
        mtf_ema50 = float(mtf_last["ema50"])
        mtf_close = float(mtf_last["close"])
        mtf_low = float(mtf_last["low"])
        mtf_high = float(mtf_last["high"])

        ltf_close = float(ltf_last["close"])
        ltf_prev_close = float(ltf_prev["close"])

        zone_low = min(mtf_ema20, mtf_ema50)
        zone_high = max(mtf_ema20, mtf_ema50)

        if direction == "LONG":
            touched_zone = mtf_low <= zone_high
            holds_zone = mtf_close >= zone_low
            reaction_up = ltf_close >= ltf_prev_close

            if not touched_zone:
                return False, "не было отката в buy-зону", 0.0
            if not holds_zone:
                return False, "цена не удержала buy-зону", 0.0
            if not reaction_up:
                return False, "нет реакции вверх после отката", 0.0

            if levels_mtf.resistance_gap_pct is not None and levels_mtf.resistance_gap_pct < 0.01:
                return False, "слишком близкое сопротивление сверху", 0.0

            entry = zone_high
            return True, "", entry

        touched_zone = mtf_high >= zone_low
        holds_zone = mtf_close <= zone_high
        reaction_down = ltf_close <= ltf_prev_close

        if not touched_zone:
            return False, "не было отката в sell-зону", 0.0
        if not holds_zone:
            return False, "цена не удержала sell-зону", 0.0
        if not reaction_down:
            return False, "нет реакции вниз после отката", 0.0

        if levels_mtf.support_gap_pct is not None and levels_mtf.support_gap_pct < 0.01:
            return False, "слишком близкая поддержка снизу", 0.0

        entry = zone_low
        return True, "", entry

    def _check_confirmation(
        self,
        direction: str,
        ltf_df: pd.DataFrame,
    ) -> tuple[bool, str]:
        last = self._closed(ltf_df)
        prev = self._prev_closed(ltf_df)

        atr_ratio_val = float(last["atr_ratio"])
        volume_ratio = float(last["quote_volume_ratio"])
        rsi = float(last["rsi"])
        macd = float(last["macd"])
        macd_signal = float(last["macd_signal"])
        macd_hist = float(last["macd_hist"])
        prev_hist = float(prev["macd_hist"])

        if atr_ratio_val < Config.MIN_ATR_RATIO_15M:
            return False, "слишком слабая волатильность"

        if volume_ratio < Config.MIN_ACCEPTABLE_QUOTE_VOLUME_RATIO:
            return False, "слабый объём подтверждения"

        if direction == "LONG":
            if rsi < 46 or rsi > 58:
                return False, "RSI вне рабочей зоны LONG"

            macd_ok = macd_hist > 0 or macd > macd_signal or macd_hist > prev_hist
            if not macd_ok:
                return False, "MACD не подтверждает LONG"

            return True, ""

        if rsi < 42 or rsi > 54:
            return False, "RSI вне рабочей зоны SHORT"

        macd_ok = macd_hist < 0 or macd < macd_signal or macd_hist < prev_hist
        if not macd_ok:
            return False, "MACD не подтверждает SHORT"

        return True, ""

    def _calculate_score(
        self,
        direction: str,
        structure_htf,
        structure_mtf,
        regime_mtf,
        levels_mtf,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0

        htf_last = self._closed(htf_df)
        mtf_last = self._closed(mtf_df)
        ltf_last = self._closed(ltf_df)

        score += 25
        reasons.append("контекст рынка согласован")

        if structure_htf.strength >= 1.0:
            score += 10
            reasons.append("HTF структура сильная")

        if structure_mtf.trend in ["UP", "DOWN"]:
            score += 10
            reasons.append("MTF структура подтверждает сценарий")

        if regime_mtf.is_trending:
            score += 10
            reasons.append("MTF в трендовом режиме")

        if float(htf_last["adx"]) >= Config.MIN_ADX_4H:
            score += 8
            reasons.append("HTF ADX подтверждает силу тренда")

        if float(mtf_last["adx"]) >= Config.MIN_ADX_1H:
            score += 7
            reasons.append("MTF ADX подтверждает движение")

        if float(ltf_last["quote_volume_ratio"]) >= 1.0:
            score += 10
            reasons.append("объём выше или около среднего")

        if direction == "LONG":
            if levels_mtf.support_gap_pct is not None and levels_mtf.support_gap_pct <= 0.02:
                score += 10
                reasons.append("рядом рабочая поддержка")

            if 46 <= float(ltf_last["rsi"]) <= 58:
                score += 10
                reasons.append("RSI в сильной LONG-зоне")

        else:
            if levels_mtf.resistance_gap_pct is not None and levels_mtf.resistance_gap_pct <= 0.02:
                score += 10
                reasons.append("рядом рабочее сопротивление")

            if 42 <= float(ltf_last["rsi"]) <= 54:
                score += 10
                reasons.append("RSI в сильной SHORT-зоне")

        return round(score, 1), reasons

    def _classify_signal(self, score: float, rr: float) -> Optional[str]:
        if score >= 70 and rr >= Config.STRONG_MIN_RR:
            return "STRONG"

        if score >= 55 and rr >= Config.SETUP_MIN_RR:
            return "SETUP"

        return None

    def analyze_symbol(
        self,
        symbol: str,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> SignalCheckResult:
        if len(htf_df) < 220 or len(mtf_df) < 220 or len(ltf_df) < 220:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason="недостаточно данных",
                diagnostics={},
            )

        htf_df = self.prepare_dataframe(htf_df)
        mtf_df = self.prepare_dataframe(mtf_df)
        ltf_df = self.prepare_dataframe(ltf_df)

        structure_htf = self.structure.detect_trend(htf_df)
        structure_mtf = self.structure.detect_trend(mtf_df)
        regime_mtf = self.regime.detect_regime(mtf_df)

        direction = self._detect_direction(structure_htf, regime_mtf)

        levels_mtf = self.levels.analyze(mtf_df, side=direction if direction != "NONE" else "NONE")

        diagnostics = self._build_diagnostics(
            htf_df=htf_df,
            mtf_df=mtf_df,
            ltf_df=ltf_df,
            structure_htf=structure_htf,
            structure_mtf=structure_mtf,
            regime_mtf=regime_mtf,
            levels_mtf=levels_mtf,
        )

        if direction == "NONE":
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason="нет согласованного направления HTF/MTF",
                diagnostics=diagnostics,
            )

        context_ok, context_reason = self._check_context(
            structure_htf=structure_htf,
            structure_mtf=structure_mtf,
            regime_mtf=regime_mtf,
            levels_mtf=levels_mtf,
        )
        if not context_ok:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=context_reason,
                diagnostics=diagnostics,
            )

        pullback_ok, pullback_reason, entry = self._check_pullback_entry(
            direction=direction,
            mtf_df=mtf_df,
            ltf_df=ltf_df,
            levels_mtf=levels_mtf,
        )
        if not pullback_ok:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=pullback_reason,
                diagnostics=diagnostics,
            )

        confirm_ok, confirm_reason = self._check_confirmation(direction, ltf_df)
        if not confirm_ok:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=confirm_reason,
                diagnostics=diagnostics,
            )

        mtf_last = self._closed(mtf_df)
        atr = float(mtf_last["atr"])

        if direction == "LONG":
            swing_low = self.structure.get_recent_swing_low(mtf_df)
            risk_report = self.risk.calculate_long(
                entry=entry,
                swing_low=swing_low,
                atr=atr,
            )
        else:
            swing_high = self.structure.get_recent_swing_high(mtf_df)
            risk_report = self.risk.calculate_short(
                entry=entry,
                swing_high=swing_high,
                atr=atr,
            )

        diagnostics["rr"] = round(float(risk_report.rr), 3) if risk_report.rr else None
        diagnostics["risk_pct"] = round(float(risk_report.risk_pct), 6) if risk_report.risk_pct else None

        if not risk_report.valid:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=risk_report.reason,
                diagnostics=diagnostics,
            )

        score, reasons = self._calculate_score(
            direction=direction,
            structure_htf=structure_htf,
            structure_mtf=structure_mtf,
            regime_mtf=regime_mtf,
            levels_mtf=levels_mtf,
            htf_df=htf_df,
            mtf_df=mtf_df,
            ltf_df=ltf_df,
        )

        diagnostics["score"] = score

        signal_type = self._classify_signal(score, risk_report.rr)
        if not signal_type:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=f"слабый сигнал: score={score}, rr={round(risk_report.rr, 2)}",
                diagnostics=diagnostics,
            )

        if signal_type == "SETUP":
            reasons.append("это SETUP-сигнал: позицию лучше брать аккуратнее")

        entry_min = entry * 0.999
        entry_max = entry * 1.001

        signal = Signal(
            symbol=symbol,
            direction=direction,
            entry_min=round(entry_min, 4),
            entry_max=round(entry_max, 4),
            stop_loss=round(risk_report.stop_loss, 4),
            tp1=round(risk_report.tp1, 4),
            tp2=round(risk_report.tp2, 4),
            tp3=round(risk_report.tp3, 4),
            score=score,
            reasons=reasons,
            diagnostics=diagnostics,
            signal_type=signal_type,
        )

        return SignalCheckResult(
            symbol=symbol,
            signal=signal,
            skip_reason="",
            diagnostics=diagnostics,
        )