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
from services.structure_engine import StructureEngine
from services.market_regime import MarketRegimeAnalyzer


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
        self.structure_engine = StructureEngine()
        self.regime_analyzer = MarketRegimeAnalyzer()
        self.levels_analyzer = LevelsAnalyzer()

    # =========================================================
    # PREPARE DATA
    # =========================================================

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

        # Денежный объем
        if "quote_asset_volume" in df.columns:
            df["quote_volume_avg_20"] = df["quote_asset_volume"].rolling(window=20).mean()
            df["quote_volume_ratio"] = df["quote_asset_volume"] / df["quote_volume_avg_20"]
        else:
            # запасной вариант
            df["quote_asset_volume"] = df["close"] * df["volume"]
            df["quote_volume_avg_20"] = df["quote_asset_volume"].rolling(window=20).mean()
            df["quote_volume_ratio"] = df["quote_asset_volume"] / df["quote_volume_avg_20"]

        return df

    def _closed(self, df: pd.DataFrame) -> pd.Series:
        return df.iloc[-2]

    def _prev_closed(self, df: pd.DataFrame) -> pd.Series:
        return df.iloc[-3]

    # =========================================================
    # DIAGNOSTICS
    # =========================================================

    def _build_diagnostics(self, htf_df: pd.DataFrame, mtf_df: pd.DataFrame, ltf_df: pd.DataFrame) -> dict:
        htf_last = self._closed(htf_df)
        mtf_last = self._closed(mtf_df)
        ltf_last = self._closed(ltf_df)

        resistance_gap = None
        support_gap = None

        if pd.notna(ltf_last["resistance"]) and ltf_last["close"] != 0:
            resistance_gap = (ltf_last["resistance"] - ltf_last["close"]) / ltf_last["close"]

        if pd.notna(ltf_last["support"]) and ltf_last["close"] != 0:
            support_gap = (ltf_last["close"] - ltf_last["support"]) / ltf_last["close"]

        return {
            "htf_adx": round(float(htf_last["adx"]), 3) if pd.notna(htf_last["adx"]) else None,
            "mtf_adx": round(float(mtf_last["adx"]), 3) if pd.notna(mtf_last["adx"]) else None,
            "ltf_rsi": round(float(ltf_last["rsi"]), 3) if pd.notna(ltf_last["rsi"]) else None,
            "ltf_macd_hist": round(float(ltf_last["macd_hist"]), 6) if pd.notna(ltf_last["macd_hist"]) else None,
            "ltf_atr_ratio": round(float(ltf_last["atr_ratio"]), 6) if pd.notna(ltf_last["atr_ratio"]) else None,
            "ltf_quote_volume_ratio": round(float(ltf_last["quote_volume_ratio"]), 3) if pd.notna(ltf_last["quote_volume_ratio"]) else None,
            "resistance_gap": round(float(resistance_gap), 6) if resistance_gap is not None else None,
            "support_gap": round(float(support_gap), 6) if support_gap is not None else None,
        }

    def _candle_metrics(self, row: pd.Series) -> dict:
        open_ = float(row["open"])
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])

        total_range = max(high - low, 1e-9)
        body = abs(close - open_)
        upper_wick = high - max(open_, close)
        lower_wick = min(open_, close) - low

        return {
            "body_ratio": body / total_range,
            "upper_wick_ratio": upper_wick / total_range,
            "lower_wick_ratio": lower_wick / total_range,
            "is_bull": close > open_,
            "is_bear": close < open_,
        }

    # =========================================================
    # REGIME FILTERS
    # =========================================================

    def _check_regime_filters(
        self,
        setup_direction: str,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> tuple[bool, str, dict]:
        htf_regime = self.regime_analyzer.detect_regime(htf_df)
        mtf_regime = self.regime_analyzer.detect_regime(mtf_df)
        ltf_regime = self.regime_analyzer.detect_regime(ltf_df)

        regime_diag = {
            "htf_regime": htf_regime.regime,
            "htf_regime_dir": htf_regime.direction,
            "mtf_regime": mtf_regime.regime,
            "mtf_regime_dir": mtf_regime.direction,
            "ltf_regime": ltf_regime.regime,
            "ltf_regime_dir": ltf_regime.direction,
        }

        # 4H range — жёсткий запрет
        if htf_regime.is_ranging:
            return False, "market regime: 4h боковик", regime_diag

        # 1H range допустим только если 4H трендовый.
        # Поэтому тут НЕ режем просто по mtf_regime.is_ranging.

        if htf_regime.is_overextended:
            return False, "market regime: 4h рынок перерастянут", regime_diag

        if mtf_regime.is_overextended and ltf_regime.is_overextended:
            return False, "market regime: 1h/15m рынок перерастянут, вход поздний", regime_diag

        if htf_regime.reversal_risk:
            return False, "market regime: высокий риск разворота на 4h", regime_diag

        if mtf_regime.reversal_risk and htf_regime.direction != setup_direction:
            return False, "market regime: высокий риск разворота на 1h", regime_diag

        wanted_dir = "LONG" if setup_direction == "LONG" else "SHORT"

        if htf_regime.direction not in {wanted_dir, "NONE"}:
            return False, "market regime: 4h направление против сигнала", regime_diag

        # 1H делаем мягче:
        # если 1H уже строго в другую сторону — skip
        if mtf_regime.direction not in {wanted_dir, "NONE"}:
            return False, "market regime: 1h направление против сигнала", regime_diag

        if not htf_regime.is_trending:
            return False, "market regime: 4h не подтверждает тренд", regime_diag

        return True, "", regime_diag

    # =========================================================
    # ENTRY QUALITY
    # =========================================================

    def _check_entry_quality(self, direction: str, ltf_df: pd.DataFrame) -> tuple[bool, str]:
        last = self._closed(ltf_df)
        prev = self._prev_closed(ltf_df)

        last_close = float(last["close"])
        ema20 = float(last["ema20"])
        ema50 = float(last["ema50"])
        atr = float(last["atr"]) if pd.notna(last["atr"]) else 0.0
        resistance = last["resistance"]
        support = last["support"]

        if atr <= 0:
            return False, "entry quality: ATR невалиден"

        dist_ema20 = abs(last_close - ema20) / last_close if last_close else 0.0
        dist_ema50 = abs(last_close - ema50) / last_close if last_close else 0.0

        # chase-фильтр: только если и от EMA20, и от EMA50 далеко
        if (
            dist_ema20 > Config.MAX_CHASE_DISTANCE_FROM_EMA20
            and dist_ema50 > Config.MAX_CHASE_DISTANCE_FROM_EMA50
        ):
            return False, "entry quality: вход слишком далеко от EMA, уже chase"

        last_candle = self._candle_metrics(last)
        prev_candle = self._candle_metrics(prev)
        body_vs_atr = abs(float(last["close"]) - float(last["open"])) / atr if atr > 0 else 0.0

        if body_vs_atr >= Config.MAX_ENTRY_BODY_ATR:
            return False, "entry quality: вход в слишком импульсную свечу"

        if direction == "LONG":
            if (
                last_candle["upper_wick_ratio"] >= Config.MAX_BAD_WICK_RATIO
                and last_candle["body_ratio"] <= 0.55
            ):
                return False, "entry quality: сильный верхний фитиль, продавец давит LONG"

            # мягкое подтверждение покупателя
            if not (
                last_candle["is_bull"]
                or (
                    prev_candle["is_bull"]
                    and float(last["low"]) >= min(float(prev["open"]), float(prev["close"]))
                )
            ):
                return False, "entry quality: нет нормального подтверждения покупателей"

            if pd.notna(resistance):
                resistance_gap = (float(resistance) - last_close) / last_close
                if resistance_gap < Config.HARD_MIN_RESISTANCE_GAP:
                    return False, "entry quality: слишком близко сопротивление"

        else:
            if (
                last_candle["lower_wick_ratio"] >= Config.MAX_BAD_WICK_RATIO
                and last_candle["body_ratio"] <= 0.55
            ):
                return False, "entry quality: сильный нижний фитиль, покупатель давит SHORT"

            # мягкое подтверждение продавца
            if not (
                last_candle["is_bear"]
                or (
                    prev_candle["is_bear"]
                    and float(last["high"]) <= max(float(prev["open"]), float(prev["close"]))
                )
            ):
                return False, "entry quality: нет нормального подтверждения продавцов"

            if pd.notna(support):
                support_gap = (last_close - float(support)) / last_close
                if support_gap < Config.HARD_MIN_SUPPORT_GAP:
                    return False, "entry quality: слишком близко поддержка"

        return True, ""

    # =========================================================
    # LEVELS CONTEXT
    # =========================================================

    def _check_levels_context(self, direction: str, ltf_df: pd.DataFrame) -> tuple[bool, str, dict]:
        if not Config.ADVANCED_LEVELS_FILTER_ENABLED:
            return True, "", {}

        report = self.levels_analyzer.analyze(ltf_df, direction)
        diagnostics = {
            "range_high": report.range_high,
            "range_low": report.range_low,
            "range_size_pct": report.range_size_pct,
            "in_middle_of_range": report.in_middle_of_range,
            "nearest_resistance": report.nearest_resistance,
            "nearest_support": report.nearest_support,
            "nearest_resistance_gap": report.resistance_gap_pct,
            "nearest_support_gap": report.support_gap_pct,
            "levels_reason": report.reason,
        }

        if (
            Config.BLOCK_MIDDLE_OF_RANGE
            and report.in_middle_of_range
            and report.range_size_pct >= Config.MIN_RANGE_SIZE_FOR_MIDDLE_FILTER
        ):
            return False, "levels: цена в середине локального диапазона", diagnostics

        if (
            direction == "LONG"
            and report.resistance_gap_pct is not None
            and report.resistance_gap_pct < Config.HARD_MIN_RESISTANCE_GAP
        ):
            return False, "levels: слишком близко ближайшее сопротивление", diagnostics

        if (
            direction == "SHORT"
            and report.support_gap_pct is not None
            and report.support_gap_pct < Config.HARD_MIN_SUPPORT_GAP
        ):
            return False, "levels: слишком близко ближайшая поддержка", diagnostics

        return True, "", diagnostics

    def _check_target_room(self, direction: str, levels: dict, diagnostics: dict) -> tuple[bool, str]:
        if not Config.TARGET_ROOM_FILTER_ENABLED:
            return True, ""

        clearance = max(Config.MIN_TP1_LEVEL_CLEARANCE, 0.0)

        if direction == "LONG":
            resistance = diagnostics.get("nearest_resistance")
            if resistance is None:
                return True, ""

            if float(levels["tp1"]) >= float(resistance) * (1 - clearance):
                return False, "levels: TP1 слишком близко к сопротивлению или за ним"

        else:
            support = diagnostics.get("nearest_support")
            if support is None:
                return True, ""

            if float(levels["tp1"]) <= float(support) * (1 + clearance):
                return False, "levels: TP1 слишком близко к поддержке или за ней"

        return True, ""

    # =========================================================
    # SETUP CHECK
    # =========================================================

    def _check_structure_setup(
        self,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ):
        return self.structure_engine.detect_setup(htf_df, mtf_df, ltf_df)

    # =========================================================
    # CONFIRMATION
    # =========================================================

    def _check_confirmation(self, direction: str, ltf_df: pd.DataFrame) -> tuple[bool, str]:
        last = self._closed(ltf_df)
        prev = self._prev_closed(ltf_df)

        if last["atr_ratio"] < Config.MIN_ATR_RATIO_15M:
            return False, "15m слишком вялый"

        if last["quote_volume_ratio"] < Config.MIN_CONFIRMATION_VOLUME_RATIO:
            return False, "15m денежный объём слишком слабый"

        last_close = float(last["close"])
        prev_close = float(prev["close"])
        ema20 = float(last["ema20"])
        ema50 = float(last["ema50"])

        if direction == "LONG":
            if last["rsi"] > Config.LONG_MAX_RSI_ENTRY:
                return False, "LONG перегрет по RSI"

            # Вход должен подтверждаться закрытием свечи в сторону LONG.
            # Это режет слабые сигналы, где цена стоит на месте или откатывает.
            if last_close <= prev_close:
                return False, "LONG нет роста закрытия свечи"

            # Цена не должна быть ниже всей рабочей EMA-зоны.
            if last_close < ema20 and last_close < ema50:
                return False, "LONG цена ниже рабочей EMA-зоны"

            macd_ok = (
                last["macd_hist"] > 0
                or last["macd"] > last["macd_signal"]
                or last["macd_hist"] > prev["macd_hist"]
            )
            if not macd_ok:
                return False, "MACD не подтверждает LONG"

            return True, ""

        if last["rsi"] < Config.SHORT_MIN_RSI_ENTRY:
            return False, "SHORT перегрет по RSI"

        # Вход должен подтверждаться закрытием свечи в сторону SHORT.
        if last_close >= prev_close:
            return False, "SHORT нет снижения закрытия свечи"

        # Цена не должна быть выше всей рабочей EMA-зоны.
        if last_close > ema20 and last_close > ema50:
            return False, "SHORT цена выше рабочей EMA-зоны"

        macd_ok = (
            last["macd_hist"] < 0
            or last["macd"] < last["macd_signal"]
            or last["macd_hist"] < prev["macd_hist"]
        )
        if not macd_ok:
            return False, "MACD не подтверждает SHORT"

        return True, ""

    # =========================================================
    # SCORE
    # =========================================================

    def calculate_score(
        self,
        setup_type: str,
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

        if direction == "LONG":
            score += 2.0
            reasons.append("структура рынка смотрит вверх")

            if setup_type == "PULLBACK_CONTINUATION":
                score += 1.6
                reasons.append("сетап: continuation after pullback")

            if setup_type == "BREAKOUT_RETEST":
                score += 1.2
                reasons.append("сетап: breakout + retest вверх")

            if htf_last["ema_fast"] > htf_last["ema_slow"]:
                score += 0.8
                reasons.append("EMA fast выше slow на 4h")

            if htf_last["adx"] >= Config.MIN_ADX_4H:
                score += 0.8
                reasons.append("4h ADX подтверждает силу тренда")

            if mtf_last["adx"] >= Config.MIN_ADX_1H:
                score += 0.6
                reasons.append("1h ADX поддерживает движение")

            if ltf_last["close"] >= ltf_last["ema20"] or ltf_last["close"] >= ltf_last["ema50"]:
                score += 0.7
                reasons.append("15m удерживает рабочую зону")

            if 48 <= ltf_last["rsi"] <= 60:
                score += 1.0
                reasons.append("RSI в нормальной зоне LONG")
            elif 60 < ltf_last["rsi"] <= Config.LONG_MAX_RSI_ENTRY:
                score += 0.3
                reasons.append("RSI выше, но ещё допустим")

            if (
                ltf_last["macd_hist"] > 0
                or ltf_last["macd"] > ltf_last["macd_signal"]
                or ltf_last["macd_hist"] > ltf_prev["macd_hist"]
            ):
                score += 0.8
                reasons.append("MACD подтверждает LONG")

            if ltf_last["quote_volume_ratio"] >= 1.0:
                score += 0.8
                reasons.append("объём на 15m не слабый")
            elif ltf_last["quote_volume_ratio"] >= 0.8:
                score += 0.4
                reasons.append("объём на 15m допустимый")

            if pd.notna(ltf_last["support"]):
                gap = (ltf_last["close"] - ltf_last["support"]) / ltf_last["close"]
                if 0 < gap <= 0.018:
                    score += 0.5
                    reasons.append("рядом поддержка")

        else:
            score += 2.0
            reasons.append("структура рынка смотрит вниз")

            if setup_type == "PULLBACK_CONTINUATION":
                score += 1.6
                reasons.append("сетап: continuation after pullback")

            if setup_type == "BREAKOUT_RETEST":
                score += 1.2
                reasons.append("сетап: breakout + retest вниз")

            if htf_last["ema_fast"] < htf_last["ema_slow"]:
                score += 0.8
                reasons.append("EMA fast ниже slow на 4h")

            if htf_last["adx"] >= Config.MIN_ADX_4H:
                score += 0.8
                reasons.append("4h ADX подтверждает силу тренда")

            if mtf_last["adx"] >= Config.MIN_ADX_1H:
                score += 0.6
                reasons.append("1h ADX поддерживает движение")

            if ltf_last["close"] <= ltf_last["ema20"] or ltf_last["close"] <= ltf_last["ema50"]:
                score += 0.7
                reasons.append("15m удерживает рабочую зону")

            if Config.SHORT_MIN_RSI_ENTRY <= ltf_last["rsi"] <= 52:
                score += 1.0
                reasons.append("RSI в нормальной зоне SHORT")
            elif 52 < ltf_last["rsi"] <= 56:
                score += 0.3
                reasons.append("RSI чуть слабее для SHORT, но допустим")

            if (
                ltf_last["macd_hist"] < 0
                or ltf_last["macd"] < ltf_last["macd_signal"]
                or ltf_last["macd_hist"] < ltf_prev["macd_hist"]
            ):
                score += 0.8
                reasons.append("MACD подтверждает SHORT")

            if ltf_last["quote_volume_ratio"] >= 1.0:
                score += 0.8
                reasons.append("объём на 15m не слабый")
            elif ltf_last["quote_volume_ratio"] >= 0.8:
                score += 0.4
                reasons.append("объём на 15m допустимый")

            if pd.notna(ltf_last["resistance"]):
                gap = (ltf_last["resistance"] - ltf_last["close"]) / ltf_last["close"]
                if 0 < gap <= 0.018:
                    score += 0.5
                    reasons.append("рядом сопротивление")

        return round(score, 1), reasons

    # =========================================================
    # LEVELS
    # =========================================================

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
            stop_loss = min(stop_loss, entry_min - stop_buffer)

            if stop_loss >= entry_min:
                return None

            risk = entry_max - stop_loss
            if risk <= 0:
                return None

            tp1 = entry_max + risk * 1.2
            tp2 = entry_max + risk * 1.8
            tp3 = entry_max + risk * 2.5

            rr = (tp1 - entry_max) / risk

            if pd.notna(resistance):
                resistance_val = float(resistance)
                if resistance_val <= entry_max:
                    return None

        else:
            anchor = max(close, ema20, ema50)
            entry_min = close * 0.999
            entry_max = anchor * 1.001

            stop_candidates = [close + atr * 1.2]
            if pd.notna(resistance):
                stop_candidates.append(float(resistance) + atr * 0.15)

            stop_loss = max(stop_candidates)
            stop_loss = max(stop_loss, entry_max + stop_buffer)

            if stop_loss <= entry_max:
                return None

            risk = stop_loss - entry_min
            if risk <= 0:
                return None

            tp1 = entry_min - risk * 1.2
            tp2 = entry_min - risk * 1.8
            tp3 = entry_min - risk * 2.5

            rr = (entry_min - tp1) / risk

            if pd.notna(support):
                support_val = float(support)
                if support_val >= entry_min:
                    return None

        entry_ref = entry_max if direction == "LONG" else entry_min
        if entry_ref <= 0:
            return None

        risk_pct = abs(entry_ref - stop_loss) / entry_ref
        tp1_distance_pct = abs(tp1 - entry_ref) / entry_ref

        # Защита от мусорных уровней на дешёвых монетах типа SLP/PEPE/SHIB:
        # после округления такие сделки выглядели как entry=stop=tp.
        if risk_pct < 0.0025:
            return None

        if tp1_distance_pct < 0.0025:
            return None

        if len({round(entry_ref, 12), round(stop_loss, 12), round(tp1, 12)}) < 3:
            return None

        return {
            "entry_min": entry_min,
            "entry_max": entry_max,
            "stop_loss": stop_loss,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "rr": rr,
        }

    # =========================================================
    # CLASSIFY
    # =========================================================

    def classify_signal(self, score: float, rr: float) -> Optional[str]:
        if score >= Config.STRONG_MIN_SCORE and rr >= Config.STRONG_MIN_RR:
            return "STRONG"

        if score >= Config.SETUP_MIN_SCORE and rr >= Config.SETUP_MIN_RR:
            return "SETUP"

        return None

    # =========================================================
    # MAIN ANALYZE
    # =========================================================

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

        setup = self._check_structure_setup(htf_df, mtf_df, ltf_df)
        if setup.setup_type == "NONE":
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=setup.reason,
                diagnostics=diagnostics,
            )

        regime_ok, regime_reason, regime_diag = self._check_regime_filters(
            setup.direction,
            htf_df,
            mtf_df,
            ltf_df,
        )
        diagnostics.update(regime_diag)
        if not regime_ok:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=regime_reason,
                diagnostics=diagnostics,
            )

        levels_ok, levels_reason, levels_diag = self._check_levels_context(setup.direction, ltf_df)
        diagnostics.update(levels_diag)
        if not levels_ok:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=levels_reason,
                diagnostics=diagnostics,
            )

        confirm_ok, confirm_reason = self._check_confirmation(setup.direction, ltf_df)
        if not confirm_ok:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=confirm_reason,
                diagnostics=diagnostics,
            )

        entry_ok, entry_reason = self._check_entry_quality(setup.direction, ltf_df)
        if not entry_ok:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=entry_reason,
                diagnostics=diagnostics,
            )

        score, reasons = self.calculate_score(
            setup.setup_type,
            setup.direction,
            htf_df,
            mtf_df,
            ltf_df,
        )
        reasons.insert(0, setup.reason)

        levels = self.build_trade_levels(setup.direction, ltf_df)
        if not levels:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason="не удалось построить entry/stop/tp",
                diagnostics=diagnostics,
            )

        target_room_ok, target_room_reason = self._check_target_room(
            setup.direction,
            levels,
            diagnostics,
        )
        if not target_room_ok:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=target_room_reason,
                diagnostics=diagnostics,
            )

        diagnostics["rr"] = round(float(levels["rr"]), 3)
        diagnostics["score"] = round(float(score), 3)
        diagnostics["setup_type"] = setup.setup_type

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
            reasons.append("это SETUP-сигнал: риск лучше держать аккуратнее")

        signal = Signal(
            symbol=symbol,
            direction=setup.direction,
            entry_min=round(levels["entry_min"], 8),
            entry_max=round(levels["entry_max"], 8),
            stop_loss=round(levels["stop_loss"], 8),
            tp1=round(levels["tp1"], 8),
            tp2=round(levels["tp2"], 8),
            tp3=round(levels["tp3"], 8),
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
