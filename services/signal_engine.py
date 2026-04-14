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
    signal_type: str  # STRONG / SETUP


@dataclass
class SignalCheckResult:
    symbol: str
    signal: Optional[Signal]
    skip_reason: str
    diagnostics: dict


class SignalEngine:
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
            resistance_gap = (ltf_last["resistance"] - ltf_last["close"]) / ltf_last["close"]

        if pd.notna(ltf_last["support"]) and ltf_last["close"] != 0:
            support_gap = (ltf_last["close"] - ltf_last["support"]) / ltf_last["close"]

        if pd.notna(ltf_last["ema20"]) and ltf_last["close"] != 0:
            dist_ema20 = abs(ltf_last["close"] - ltf_last["ema20"]) / ltf_last["close"]

        if pd.notna(ltf_last["ema50"]) and ltf_last["close"] != 0:
            dist_ema50 = abs(ltf_last["close"] - ltf_last["ema50"]) / ltf_last["close"]

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
            "ltf_close": round(float(ltf_last["close"]), 6) if pd.notna(ltf_last["close"]) else None,
        }

    def detect_trend(self, htf_df: pd.DataFrame) -> str:
        last = self._closed(htf_df)

        if (
            last["close"] > last["ema_slow"]
            and last["ema_fast"] > last["ema_slow"]
            and last["adx"] >= Config.MIN_ADX_4H
        ):
            return "LONG"

        if (
            last["close"] < last["ema_slow"]
            and last["ema_fast"] < last["ema_slow"]
            and last["adx"] >= Config.MIN_ADX_4H
        ):
            return "SHORT"

        return "NONE"

    def _check_mtf_alignment(self, direction: str, mtf_df: pd.DataFrame) -> tuple[bool, str]:
        last = self._closed(mtf_df)

        if direction == "LONG":
            if last["close"] <= last["ema50"]:
                return False, "1h не подтверждает LONG: цена ниже EMA50"
            if last["adx"] < Config.MIN_ADX_1H:
                return False, "1h не подтверждает LONG: слабый ADX"
            return True, ""

        if last["close"] >= last["ema50"]:
            return False, "1h не подтверждает SHORT: цена выше EMA50"
        if last["adx"] < Config.MIN_ADX_1H:
            return False, "1h не подтверждает SHORT: слабый ADX"
        return True, ""

    def _check_quote_volume(self, ltf_df: pd.DataFrame) -> tuple[bool, str]:
        last = self._closed(ltf_df)

        if pd.isna(last["quote_volume_avg_20"]) or last["quote_volume_avg_20"] <= 0:
            return False, "15m недостаточно данных по денежному объёму"

        volume_ratio = last["quote_volume_ratio"]

        if pd.isna(volume_ratio):
            return False, "15m не удалось рассчитать денежный объём"

        if volume_ratio < Config.MIN_ACCEPTABLE_QUOTE_VOLUME_RATIO:
            return False, "15m денежный объём слишком слабый"

        return True, ""

    def _check_not_chasing(self, direction: str, ltf_df: pd.DataFrame) -> tuple[bool, str]:
        last = self._closed(ltf_df)

        dist_ema20 = abs(last["close"] - last["ema20"]) / last["close"]
        dist_ema50 = abs(last["close"] - last["ema50"]) / last["close"]

        if direction == "LONG":
            if last["rsi"] > Config.LONG_MAX_RSI_ENTRY:
                return False, "anti-fomo: LONG перегрет по RSI"

            if dist_ema20 > Config.MAX_CHASE_DISTANCE_FROM_EMA20 and dist_ema50 > Config.MAX_CHASE_DISTANCE_FROM_EMA50:
                return False, "anti-fomo: LONG слишком далеко от EMA20/EMA50"

            if pd.notna(last["resistance"]):
                gap_to_resistance = (last["resistance"] - last["close"]) / last["close"]
                if gap_to_resistance <= 0:
                    return False, "цена уже в сопротивлении"
                if gap_to_resistance < Config.HARD_MIN_RESISTANCE_GAP:
                    return False, "anti-fomo: слишком близкое сопротивление сверху"

            return True, ""

        if last["rsi"] < Config.SHORT_MIN_RSI_ENTRY:
            return False, "anti-fomo: SHORT перегрет по RSI"

        if dist_ema20 > Config.MAX_CHASE_DISTANCE_FROM_EMA20 and dist_ema50 > Config.MAX_CHASE_DISTANCE_FROM_EMA50:
            return False, "anti-fomo: SHORT слишком далеко от EMA20/EMA50"

        if pd.notna(last["support"]):
            gap_to_support = (last["close"] - last["support"]) / last["close"]
            if gap_to_support <= 0:
                return False, "цена уже в поддержке"
            if gap_to_support < Config.HARD_MIN_SUPPORT_GAP:
                return False, "anti-fomo: слишком близкая поддержка снизу"

        return True, ""

    def _check_retest_zone(self, direction: str, ltf_df: pd.DataFrame) -> tuple[bool, str]:
        last = self._closed(ltf_df)

        dist_ema20 = abs(last["close"] - last["ema20"]) / last["close"]
        dist_ema50 = abs(last["close"] - last["ema50"]) / last["close"]

        if dist_ema20 > Config.MAX_DISTANCE_FROM_EMA20 and dist_ema50 > Config.MAX_DISTANCE_FROM_EMA50:
            return False, "цена слишком далеко от EMA20/EMA50, вход поздний"

        if direction == "LONG":
            if last["close"] < last["ema20"] and last["close"] < last["ema50"]:
                return False, "15m не удержал зону EMA20/EMA50 для LONG"
            return True, ""

        if last["close"] > last["ema20"] and last["close"] > last["ema50"]:
            return False, "15m не удержал зону EMA20/EMA50 для SHORT"
        return True, ""

    def _check_ltf_quality(self, direction: str, ltf_df: pd.DataFrame) -> tuple[bool, str]:
        last = self._closed(ltf_df)
        prev = self._prev_closed(ltf_df)

        if last["atr_ratio"] < Config.MIN_ATR_RATIO_15M:
            return False, "15m слишком вялый: ATR ratio ниже минимума"

        anti_fomo_ok, anti_fomo_reason = self._check_not_chasing(direction, ltf_df)
        if not anti_fomo_ok:
            return False, anti_fomo_reason

        zone_ok, zone_reason = self._check_retest_zone(direction, ltf_df)
        if not zone_ok:
            return False, zone_reason

        volume_ok, volume_reason = self._check_quote_volume(ltf_df)
        if not volume_ok:
            return False, volume_reason

        if direction == "LONG":
            if not (46 <= last["rsi"] <= 68):
                return False, "15m RSI вне зоны качественного LONG-входа"

            macd_ok = (
                last["macd_hist"] > 0
                or last["macd"] > last["macd_signal"]
                or last["macd_hist"] > prev["macd_hist"]
            )
            if not macd_ok:
                return False, "15m MACD не подтверждает LONG"

            return True, ""

        if not (32 <= last["rsi"] <= 54):
            return False, "15m RSI вне зоны качественного SHORT-входа"

        macd_ok = (
            last["macd_hist"] < 0
            or last["macd"] < last["macd_signal"]
            or last["macd_hist"] < prev["macd_hist"]
        )
        if not macd_ok:
            return False, "15m MACD не подтверждает SHORT"

        return True, ""

    def calculate_score(
        self,
        direction: str,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons = []

        htf_last = self._closed(htf_df)
        mtf_last = self._closed(mtf_df)
        ltf_last = self._closed(ltf_df)
        ltf_prev = self._prev_closed(ltf_df)

        volume_ratio = ltf_last["quote_volume_ratio"]

        if direction == "LONG":
            score += 2.0
            reasons.append("тренд 4h восходящий")

            if htf_last["ema_fast"] > htf_last["ema_slow"]:
                score += 1.0
                reasons.append("EMA 50 выше EMA 200 на 4h")

            if htf_last["adx"] >= Config.MIN_ADX_4H + 4:
                score += 0.8
                reasons.append("4h ADX показывает силу тренда")

            if mtf_last["close"] > mtf_last["ema50"]:
                score += 1.0
                reasons.append("1h подтверждает направление")

            if mtf_last["adx"] >= Config.MIN_ADX_1H + 3:
                score += 0.7
                reasons.append("1h ADX подтверждает импульс")

            if ltf_last["close"] >= ltf_last["ema20"] or ltf_last["close"] >= ltf_last["ema50"]:
                score += 0.8
                reasons.append("15m держится над зоной EMA20/EMA50")

            if 49 <= ltf_last["rsi"] <= 58:
                score += 1.0
                reasons.append("RSI на 15m в рабочей зоне роста без перегрева")
            elif 58 < ltf_last["rsi"] <= Config.LONG_MAX_RSI_ENTRY:
                score += 0.4
                reasons.append("RSI на 15m ближе к перегреву, но ещё допустим")

            if (
                ltf_last["macd_hist"] > 0
                or ltf_last["macd"] > ltf_last["macd_signal"]
                or ltf_last["macd_hist"] > ltf_prev["macd_hist"]
            ):
                score += 0.9
                reasons.append("MACD на 15m поддерживает LONG")

            if pd.notna(volume_ratio):
                if volume_ratio >= 1.15:
                    score += 1.1
                    reasons.append("денежный объём на 15m выше среднего")
                elif volume_ratio >= 1.00:
                    score += 0.8
                    reasons.append("денежный объём на 15m нормальный")
                elif volume_ratio >= 0.85:
                    score += 0.4
                    reasons.append("денежный объём на 15m немного ниже среднего, но допустим")

            if pd.notna(ltf_last["support"]):
                gap = (ltf_last["close"] - ltf_last["support"]) / ltf_last["close"]
                if 0 < gap <= 0.015:
                    score += 0.8
                    reasons.append("рядом swing-поддержка")

        else:
            score += 2.0
            reasons.append("тренд 4h нисходящий")

            if htf_last["ema_fast"] < htf_last["ema_slow"]:
                score += 1.0
                reasons.append("EMA 50 ниже EMA 200 на 4h")

            if htf_last["adx"] >= Config.MIN_ADX_4H + 4:
                score += 0.8
                reasons.append("4h ADX показывает силу тренда")

            if mtf_last["close"] < mtf_last["ema50"]:
                score += 1.0
                reasons.append("1h подтверждает направление")

            if mtf_last["adx"] >= Config.MIN_ADX_1H + 3:
                score += 0.7
                reasons.append("1h ADX подтверждает импульс")

            if ltf_last["close"] <= ltf_last["ema20"] or ltf_last["close"] <= ltf_last["ema50"]:
                score += 0.8
                reasons.append("15m держится под зоной EMA20/EMA50")

            if Config.SHORT_MIN_RSI_ENTRY <= ltf_last["rsi"] <= 50:
                score += 1.0
                reasons.append("RSI на 15m в рабочей зоне снижения без перегрева")
            elif 50 < ltf_last["rsi"] <= 54:
                score += 0.4
                reasons.append("RSI на 15m хуже для SHORT, но ещё допустим")

            if (
                ltf_last["macd_hist"] < 0
                or ltf_last["macd"] < ltf_last["macd_signal"]
                or ltf_last["macd_hist"] < ltf_prev["macd_hist"]
            ):
                score += 0.9
                reasons.append("MACD на 15m поддерживает SHORT")

            if pd.notna(volume_ratio):
                if volume_ratio >= 1.15:
                    score += 1.1
                    reasons.append("денежный объём на 15m выше среднего")
                elif volume_ratio >= 1.00:
                    score += 0.8
                    reasons.append("денежный объём на 15m нормальный")
                elif volume_ratio >= 0.85:
                    score += 0.4
                    reasons.append("денежный объём на 15m немного ниже среднего, но допустим")

            if pd.notna(ltf_last["resistance"]):
                gap = (ltf_last["resistance"] - ltf_last["close"]) / ltf_last["close"]
                if 0 < gap <= 0.015:
                    score += 0.8
                    reasons.append("рядом swing-сопротивление")

        return round(score, 1), reasons

    def build_trade_levels(self, direction: str, ltf_df: pd.DataFrame):
        last = self._closed(ltf_df)
        atr = float(last["atr"])
        close = float(last["close"])
        support = last["support"]
        resistance = last["resistance"]
        ema20 = float(last["ema20"])
        ema50 = float(last["ema50"])

        if pd.isna(atr) or atr <= 0:
            return None

        stop_buffer = atr * Config.MIN_STOP_BUFFER_ATR

        if direction == "LONG":
            anchor = min(close, ema20, ema50)
            entry_min = anchor * 0.999
            entry_max = close * 1.001

            stop_candidates = [close - atr * 1.2]
            if pd.notna(support):
                stop_candidates.append(float(support) - atr * 0.15)

            stop_loss = min(stop_candidates)

            max_allowed_stop = entry_min - stop_buffer
            stop_loss = min(stop_loss, max_allowed_stop)

            if stop_loss >= entry_min:
                return None

            risk = entry_max - stop_loss
            if risk <= 0:
                return None

            tp1 = entry_max + risk * 1.8
            tp2 = entry_max + risk * 2.6
            tp3 = entry_max + risk * 3.5

            rr = (tp1 - entry_max) / risk

            if pd.notna(resistance):
                resistance = float(resistance)
                if resistance <= entry_max:
                    return None
                if resistance < tp1:
                    rr = min(rr, (resistance - entry_max) / risk)

        else:
            anchor = max(close, ema20, ema50)
            entry_min = close * 0.999
            entry_max = anchor * 1.001

            stop_candidates = [close + atr * 1.2]
            if pd.notna(resistance):
                stop_candidates.append(float(resistance) + atr * 0.15)

            stop_loss = max(stop_candidates)

            min_allowed_stop = entry_max + stop_buffer
            stop_loss = max(stop_loss, min_allowed_stop)

            if stop_loss <= entry_max:
                return None

            risk = stop_loss - entry_min
            if risk <= 0:
                return None

            tp1 = entry_min - risk * 1.8
            tp2 = entry_min - risk * 2.6
            tp3 = entry_min - risk * 3.5

            rr = (entry_min - tp1) / risk

            if pd.notna(support):
                support = float(support)
                if support >= entry_min:
                    return None
                if support > tp1:
                    rr = min(rr, (entry_min - support) / risk)

        return {
            "entry_min": entry_min,
            "entry_max": entry_max,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "rr": rr,
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

        direction = self.detect_trend(htf_df)
        if direction == "NONE":
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason="нет сильного тренда на 4h",
                diagnostics=diagnostics,
            )

        mtf_ok, mtf_reason = self._check_mtf_alignment(direction, mtf_df)
        if not mtf_ok:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=mtf_reason,
                diagnostics=diagnostics,
            )

        ltf_ok, ltf_reason = self._check_ltf_quality(direction, ltf_df)
        if not ltf_ok:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=ltf_reason,
                diagnostics=diagnostics,
            )

        score, reasons = self.calculate_score(direction, htf_df, mtf_df, ltf_df)
        levels = self.build_trade_levels(direction, ltf_df)

        if not levels:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason="не удалось построить entry/stop/tp",
                diagnostics=diagnostics,
            )

        diagnostics["rr"] = round(float(levels["rr"]), 3)
        diagnostics["score"] = round(float(score), 3)

        signal_type = self.classify_signal(score, levels["rr"])
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
            reasons = reasons + ["сетап ниже уровня STRONG, нужен более аккуратный риск"]

        signal = Signal(
            symbol=symbol,
            direction=direction,
            entry_min=round(levels["entry_min"], 4),
            entry_max=round(levels["entry_max"], 4),
            stop_loss=round(levels["stop_loss"], 4),
            tp1=round(levels["tp1"], 4),
            tp2=round(levels["tp2"], 4),
            tp3=round(levels["tp3"], 4),
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