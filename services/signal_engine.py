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
from services.structure_engine import StructureEngine, SetupDecision


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
        self.structure = StructureEngine()

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

    def _build_diagnostics(self, htf_df: pd.DataFrame, mtf_df: pd.DataFrame, ltf_df: pd.DataFrame) -> dict:
        htf_last = self._closed(htf_df)
        mtf_last = self._closed(mtf_df)
        ltf_last = self._closed(ltf_df)

        resistance_gap = None
        support_gap = None
        dist_ema20 = None
        dist_ema50 = None

        if pd.notna(ltf_last["resistance"]) and ltf_last["close"] != 0:
            resistance_gap = (float(ltf_last["resistance"]) - float(ltf_last["close"])) / float(ltf_last["close"])

        if pd.notna(ltf_last["support"]) and ltf_last["close"] != 0:
            support_gap = (float(ltf_last["close"]) - float(ltf_last["support"])) / float(ltf_last["close"])

        if pd.notna(ltf_last["ema20"]) and ltf_last["close"] != 0:
            dist_ema20 = abs(float(ltf_last["close"]) - float(ltf_last["ema20"])) / float(ltf_last["close"])

        if pd.notna(ltf_last["ema50"]) and ltf_last["close"] != 0:
            dist_ema50 = abs(float(ltf_last["close"]) - float(ltf_last["ema50"])) / float(ltf_last["close"])

        return {
            "htf_adx": round(float(htf_last["adx"]), 3) if pd.notna(htf_last["adx"]) else None,
            "mtf_adx": round(float(mtf_last["adx"]), 3) if pd.notna(mtf_last["adx"]) else None,
            "ltf_rsi": round(float(ltf_last["rsi"]), 3) if pd.notna(ltf_last["rsi"]) else None,
            "ltf_macd_hist": round(float(ltf_last["macd_hist"]), 6) if pd.notna(ltf_last["macd_hist"]) else None,
            "ltf_atr_ratio": round(float(ltf_last["atr_ratio"]), 6) if pd.notna(ltf_last["atr_ratio"]) else None,
            "ltf_quote_volume_ratio": round(float(ltf_last["quote_volume_ratio"]), 3) if pd.notna(ltf_last["quote_volume_ratio"]) else None,
            "resistance_gap": round(float(resistance_gap), 6) if resistance_gap is not None else None,
            "support_gap": round(float(support_gap), 6) if support_gap is not None else None,
            "dist_ema20": round(float(dist_ema20), 6) if dist_ema20 is not None else None,
            "dist_ema50": round(float(dist_ema50), 6) if dist_ema50 is not None else None,
        }

    def _check_confirmation(self, direction: str, ltf_df: pd.DataFrame) -> tuple[bool, str]:
        last = self._closed(ltf_df)
        prev = self._prev_closed(ltf_df)

        if float(last["atr_ratio"]) < Config.MIN_ATR_RATIO_15M:
            return False, "15m слишком вялый"

        if float(last["quote_volume_ratio"]) < Config.MIN_ACCEPTABLE_QUOTE_VOLUME_RATIO:
            return False, "15m денежный объём слишком слабый"

        if direction == "LONG":
            if float(last["rsi"]) > 58:
                return False, "LONG уже перегрет по RSI"

            if float(last["close"]) < float(last["ema20"]) and float(last["close"]) < float(last["ema50"]):
                return False, "LONG не удерживает зону EMA20/EMA50"

            macd_ok = (
                float(last["macd_hist"]) > 0
                or float(last["macd"]) > float(last["macd_signal"])
                or float(last["macd_hist"]) > float(prev["macd_hist"])
            )
            if not macd_ok:
                return False, "MACD не подтверждает LONG"

            return True, ""

        if float(last["rsi"]) < 42:
            return False, "SHORT уже перегрет по RSI"

        if float(last["close"]) > float(last["ema20"]) and float(last["close"]) > float(last["ema50"]):
            return False, "SHORT не удерживает зону EMA20/EMA50"

        macd_ok = (
            float(last["macd_hist"]) < 0
            or float(last["macd"]) < float(last["macd_signal"])
            or float(last["macd_hist"]) < float(prev["macd_hist"])
        )
        if not macd_ok:
            return False, "MACD не подтверждает SHORT"

        return True, ""

    def calculate_score(
        self,
        setup: SetupDecision,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []

        htf_last = self._closed(htf_df)
        mtf_last = self._closed(mtf_df)
        ltf_last = self._closed(ltf_df)
        ltf_prev = self._prev_closed(ltf_df)

        score += 2.0
        reasons.append(setup.reason)

        if setup.setup_type == "TREND_PULLBACK":
            score += 1.8
            reasons.append("сетап: trend pullback")

        if setup.direction == "LONG":
            if float(htf_last["ema_fast"]) > float(htf_last["ema_slow"]):
                score += 0.8
                reasons.append("EMA 50 выше EMA 200 на 4h")

            if float(htf_last["adx"]) >= Config.MIN_ADX_4H:
                score += 0.8
                reasons.append("4h ADX подтверждает силу тренда")

            if float(mtf_last["adx"]) >= Config.MIN_ADX_1H:
                score += 0.6
                reasons.append("1h ADX поддерживает движение")

            if 47 <= float(ltf_last["rsi"]) <= 58:
                score += 0.9
                reasons.append("RSI в рабочей зоне LONG")

            if (
                float(ltf_last["macd_hist"]) > 0
                or float(ltf_last["macd"]) > float(ltf_last["macd_signal"])
                or float(ltf_last["macd_hist"]) > float(ltf_prev["macd_hist"])
            ):
                score += 0.8
                reasons.append("MACD подтверждает LONG")

            if float(ltf_last["quote_volume_ratio"]) >= 1.0:
                score += 0.8
                reasons.append("объём не слабый")

        else:
            if float(htf_last["ema_fast"]) < float(htf_last["ema_slow"]):
                score += 0.8
                reasons.append("EMA 50 ниже EMA 200 на 4h")

            if float(htf_last["adx"]) >= Config.MIN_ADX_4H:
                score += 0.8
                reasons.append("4h ADX подтверждает силу тренда")

            if float(mtf_last["adx"]) >= Config.MIN_ADX_1H:
                score += 0.6
                reasons.append("1h ADX поддерживает движение")

            if 42 <= float(ltf_last["rsi"]) <= 53:
                score += 0.9
                reasons.append("RSI в рабочей зоне SHORT")

            if (
                float(ltf_last["macd_hist"]) < 0
                or float(ltf_last["macd"]) < float(ltf_last["macd_signal"])
                or float(ltf_last["macd_hist"]) < float(ltf_prev["macd_hist"])
            ):
                score += 0.8
                reasons.append("MACD подтверждает SHORT")

            if float(ltf_last["quote_volume_ratio"]) >= 1.0:
                score += 0.8
                reasons.append("объём не слабый")

        return round(score, 1), reasons

    def build_trade_levels(self, setup: SetupDecision, ltf_df: pd.DataFrame):
        last = self._closed(ltf_df)

        close = float(last["close"])
        ema20 = float(last["ema20"])
        ema50 = float(last["ema50"])
        atr = float(last["atr"])

        if atr <= 0:
            return None

        zone_low = float(setup.zone_low) if setup.zone_low is not None else min(ema20, ema50)
        zone_high = float(setup.zone_high) if setup.zone_high is not None else max(ema20, ema50)
        invalidation = float(setup.invalidation) if setup.invalidation is not None else None

        if invalidation is None:
            return None

        if setup.direction == "LONG":
            entry_min = zone_low
            entry_max = min(zone_high * 1.002, close * 1.0015)

            if entry_max <= entry_min:
                entry_max = entry_min * 1.002

            stop_loss = invalidation - atr * 0.20

            if stop_loss >= entry_min:
                return None

            risk = entry_max - stop_loss
            if risk <= 0:
                return None

            tp1 = entry_max + risk * 1.8
            tp2 = entry_max + risk * 2.5
            tp3 = entry_max + risk * 3.2
            rr = (tp1 - entry_max) / risk

        else:
            entry_min = max(zone_low * 0.998, close * 0.9985)
            entry_max = zone_high

            if entry_max <= entry_min:
                entry_min = entry_max * 0.998

            stop_loss = invalidation + atr * 0.20

            if stop_loss <= entry_max:
                return None

            risk = stop_loss - entry_min
            if risk <= 0:
                return None

            tp1 = entry_min - risk * 1.8
            tp2 = entry_min - risk * 2.5
            tp3 = entry_min - risk * 3.2
            rr = (entry_min - tp1) / risk

        stop_distance_ratio = abs(((entry_min + entry_max) / 2) - stop_loss) / ((entry_min + entry_max) / 2)

        return {
            "entry_min": entry_min,
            "entry_max": entry_max,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "rr": rr,
            "stop_distance_ratio": stop_distance_ratio,
        }

    def classify_signal(self, score: float, rr: float) -> Optional[str]:
        if score >= Config.STRONG_MIN_SCORE and rr >= Config.STRONG_MIN_RR:
            return "STRONG"

        if score >= Config.SETUP_MIN_SCORE and rr >= Config.SETUP_MIN_RR:
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
                skip_reason="недостаточно свечей для анализа",
                diagnostics={},
            )

        htf_df = self.prepare_dataframe(htf_df)
        mtf_df = self.prepare_dataframe(mtf_df)
        ltf_df = self.prepare_dataframe(ltf_df)

        diagnostics = self._build_diagnostics(htf_df, mtf_df, ltf_df)

        setup = self.structure.detect_setup(htf_df, mtf_df, ltf_df)
        if not setup.valid:
            diagnostics["setup_type"] = setup.setup_type
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=setup.reason,
                diagnostics=diagnostics,
            )

        confirm_ok, confirm_reason = self._check_confirmation(setup.direction, ltf_df)
        if not confirm_ok:
            diagnostics["setup_type"] = setup.setup_type
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=confirm_reason,
                diagnostics=diagnostics,
            )

        score, reasons = self.calculate_score(setup, htf_df, mtf_df, ltf_df)
        levels = self.build_trade_levels(setup, ltf_df)

        if not levels:
            diagnostics["setup_type"] = setup.setup_type
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason="не удалось построить нормальный entry/stop",
                diagnostics=diagnostics,
            )

        diagnostics["rr"] = round(float(levels["rr"]), 3)
        diagnostics["score"] = round(float(score), 3)
        diagnostics["setup_type"] = setup.setup_type
        diagnostics["stop_distance_ratio"] = round(float(levels["stop_distance_ratio"]), 6)

        if float(levels["stop_distance_ratio"]) < 0.0025:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason="стоп слишком близкий, сделка хрупкая",
                diagnostics=diagnostics,
            )

        signal_type = self.classify_signal(score, float(levels["rr"]))
        if not signal_type:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=(
                    f"слабый сигнал: score={score} / rr={levels['rr']:.3f} "
                    f"(strong: {Config.STRONG_MIN_SCORE}/{Config.STRONG_MIN_RR}, "
                    f"setup: {Config.SETUP_MIN_SCORE}/{Config.SETUP_MIN_RR})"
                ),
                diagnostics=diagnostics,
            )

        if signal_type == "SETUP":
            reasons.append("это SETUP-сигнал: размер позиции лучше уменьшать")

        signal = Signal(
            symbol=symbol,
            direction=setup.direction,
            entry_min=round(float(levels["entry_min"]), 4),
            entry_max=round(float(levels["entry_max"]), 4),
            stop_loss=round(float(levels["stop_loss"]), 4),
            tp1=round(float(levels["tp1"]), 4),
            tp2=round(float(levels["tp2"]), 4),
            tp3=round(float(levels["tp3"]), 4),
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