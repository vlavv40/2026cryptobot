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
from services.structure_engine import SetupContext, StructureEngine
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
            "htf_regime_reason": htf_regime.reason,
            "mtf_regime": mtf_regime.regime,
            "mtf_regime_dir": mtf_regime.direction,
            "mtf_regime_reason": mtf_regime.reason,
            "ltf_regime": ltf_regime.regime,
            "ltf_regime_dir": ltf_regime.direction,
            "ltf_regime_reason": ltf_regime.reason,
        }

        if htf_regime.is_volatility_compression:
            return False, "market regime: 4h сжатие волатильности, нет follow-through", regime_diag

        # 4H range — жёсткий запрет
        if htf_regime.is_ranging and not htf_regime.is_volatility_expansion:
            return False, "market regime: 4h боковик", regime_diag

        # 1H range допустим только если 4H трендовый.
        # Поэтому тут НЕ режем просто по mtf_regime.is_ranging.
        if mtf_regime.is_volatility_compression and ltf_regime.is_volatility_compression:
            return False, "market regime: 1h/15m сжатие волатильности", regime_diag

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

        if not (htf_regime.is_trending or htf_regime.is_volatility_expansion):
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

        atr_ratio_value = self._safe_float(last.get("atr_ratio"))
        volume_ratio = self._safe_float(last.get("quote_volume_ratio"), 1.0)
        adx = self._safe_float(last.get("adx"))
        min_atr_ratio = Config.MIN_ATR_RATIO_15M
        min_volume_ratio = Config.MIN_CONFIRMATION_VOLUME_RATIO

        if Config.STRATEGY_MODE != "SNIPER":
            min_atr_ratio = min(min_atr_ratio, Config.MIN_SETUP_ATR_RATIO)
            if adx >= 22:
                min_atr_ratio = min(min_atr_ratio, Config.MIN_SETUP_ATR_RATIO * 0.85)
            min_volume_ratio = min(min_volume_ratio, Config.MIN_SETUP_VOLUME_RATIO)
            if adx >= 24:
                min_volume_ratio = min(min_volume_ratio, 0.35)

        if atr_ratio_value < min_atr_ratio:
            return False, "15m слишком вялый"

        if volume_ratio < min_volume_ratio:
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

            if setup_type == "MOMENTUM_CONTINUATION":
                score += 1.0
                reasons.append("сетап: trend/momentum continuation вверх")

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

            if setup_type == "MOMENTUM_CONTINUATION":
                score += 1.0
                reasons.append("сетап: trend/momentum continuation вниз")

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

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            if pd.isna(value):
                return default
            return float(value)
        except Exception:
            return default

    def _clamp(self, value: float, min_value: float, max_value: float) -> float:
        return max(min_value, min(value, max_value))

    def _dedupe_levels(self, levels: list[float], tolerance: float) -> list[float]:
        clean = []

        for level in sorted(levels):
            if level <= 0:
                continue

            if clean and abs(level - clean[-1]) <= tolerance:
                continue

            clean.append(level)

        return clean

    def _symbol_profile(self, symbol: str, last: pd.Series) -> dict:
        quote_volume_avg = self._safe_float(last.get("quote_volume_avg_20"))
        atr_ratio_value = self._safe_float(last.get("atr_ratio"))
        symbol = symbol.upper()

        majors = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"}

        if symbol in majors or quote_volume_avg >= 50_000_000:
            max_stop_atr = Config.MAX_STOP_ATR_MAJOR
            max_stop_pct = Config.MAX_STOP_PCT_MAJOR
            buffer_atr = 0.16
            liquidity = "HIGH"
        elif quote_volume_avg and quote_volume_avg < 2_500_000:
            max_stop_atr = Config.MAX_STOP_ATR_LOW_LIQUIDITY
            max_stop_pct = Config.MAX_STOP_PCT_LOW_LIQUIDITY
            buffer_atr = 0.26
            liquidity = "LOW"
        else:
            max_stop_atr = Config.MAX_STOP_ATR_DEFAULT
            max_stop_pct = Config.MAX_STOP_PCT_DEFAULT
            buffer_atr = 0.20
            liquidity = "NORMAL"

        if atr_ratio_value >= 0.008:
            max_stop_atr += 0.12
            buffer_atr += 0.04
        elif 0 < atr_ratio_value <= 0.0035:
            max_stop_atr -= 0.08
            buffer_atr -= 0.03

        return {
            "liquidity": liquidity,
            "max_stop_atr": max(0.85, max_stop_atr),
            "max_stop_pct": max_stop_pct,
            "buffer_atr": self._clamp(buffer_atr, 0.12, 0.32),
        }

    def _recent_structure_levels(self, ltf_df: pd.DataFrame, entry_ref: float, atr: float) -> dict:
        window = ltf_df.iloc[-62:-2].copy()
        tolerance = max(atr * 0.25, entry_ref * 0.001)

        supports = []
        resistances = []

        if len(window) >= 5:
            lows = [float(x) for x in window["low"].dropna().tolist()]
            highs = [float(x) for x in window["high"].dropna().tolist()]

            supports.extend([x for x in lows if x < entry_ref])
            resistances.extend([x for x in highs if x > entry_ref])

            rolling_low = window["low"].rolling(window=5).min().dropna()
            rolling_high = window["high"].rolling(window=5).max().dropna()

            supports.extend([float(x) for x in rolling_low.tolist() if float(x) < entry_ref])
            resistances.extend([float(x) for x in rolling_high.tolist() if float(x) > entry_ref])

        return {
            "supports": self._dedupe_levels(supports, tolerance),
            "resistances": self._dedupe_levels(resistances, tolerance),
        }

    def _pick_take_profit_level(
        self,
        direction: str,
        entry_ref: float,
        risk: float,
        levels: list[float],
        min_rr: float,
        fallback_rr: float,
    ) -> float:
        if direction == "LONG":
            for level in levels:
                rr = (level - entry_ref) / risk
                if rr < min_rr:
                    continue
                if rr <= fallback_rr + 0.35:
                    return level
            return entry_ref + risk * fallback_rr

        for level in sorted(levels, reverse=True):
            rr = (entry_ref - level) / risk
            if rr < min_rr:
                continue
            if rr <= fallback_rr + 0.35:
                return level
        return entry_ref - risk * fallback_rr

    def build_trade_levels(self, symbol: str, direction: str, ltf_df: pd.DataFrame):
        last = self._closed(ltf_df)
        atr = float(last["atr"])
        close = float(last["close"])
        support = last["support"]
        resistance = last["resistance"]
        ema20 = float(last["ema20"])
        ema50 = float(last["ema50"])

        if pd.isna(atr) or atr <= 0:
            return None

        profile = self._symbol_profile(symbol, last)
        stop_buffer = atr * profile["buffer_atr"]

        if direction == "LONG":
            anchor = min(close, ema20, ema50)
            entry_min = max(
                anchor * 0.999,
                close - atr * Config.MAX_ENTRY_ZONE_ATR,
                close * (1 - Config.MAX_ENTRY_ZONE_PCT),
            )
            entry_max = close * 1.001
            entry_ref = entry_max

            structure = self._recent_structure_levels(ltf_df, entry_ref, atr)
            stop_candidates = [close - atr * profile["max_stop_atr"], ema50 - stop_buffer]
            if pd.notna(support):
                stop_candidates.append(float(support) - stop_buffer)

            if structure["supports"]:
                stop_candidates.append(max(structure["supports"]) - stop_buffer)

            stop_candidates = [x for x in stop_candidates if x < entry_min]
            if not stop_candidates:
                stop_candidates = [entry_min - stop_buffer]

            stop_loss = max(stop_candidates)
            max_stop_distance = min(
                atr * profile["max_stop_atr"],
                entry_ref * profile["max_stop_pct"],
            )
            stop_loss = max(stop_loss, entry_ref - max_stop_distance)
            stop_loss = min(stop_loss, entry_min - stop_buffer)

            if stop_loss >= entry_min:
                return None

            risk = entry_max - stop_loss
            if risk <= 0:
                return None

            trend_strength = self._clamp((self._safe_float(last.get("adx")) - 14) / 26, 0.0, 1.0)
            tp1_rr = self._clamp(1.05 + trend_strength * 0.25, Config.TP1_MIN_RR, Config.TP1_MAX_RR)
            tp2_rr = self._clamp(tp1_rr + 0.48 + trend_strength * 0.18, 1.48, 1.95)
            tp3_rr = self._clamp(tp2_rr + 0.55 + trend_strength * 0.18, 2.05, Config.TP3_MAX_RR)

            resistance_levels = structure["resistances"]

            if pd.notna(resistance):
                resistance_val = float(resistance)
                if resistance_val > entry_ref:
                    resistance_levels.append(resistance_val)

            resistance_levels = self._dedupe_levels(
                [x for x in resistance_levels if x > entry_ref],
                max(atr * 0.25, entry_ref * 0.001),
            )

            nearest_resistance_rr = None
            if resistance_levels:
                nearest_resistance_rr = (resistance_levels[0] - entry_ref) / risk
                if nearest_resistance_rr < Config.TP1_MIN_RR:
                    target_distance = resistance_levels[0] - entry_ref
                    desired_risk = target_distance / Config.TP1_MIN_RR
                    min_risk = entry_ref * 0.0025
                    min_stop_gap = max(stop_buffer * 0.25, entry_ref * 0.0005)
                    tightened_stop = min(entry_ref - desired_risk, entry_min - min_stop_gap)

                    if desired_risk < min_risk or tightened_stop >= entry_min:
                        return None

                    stop_loss = max(stop_loss, tightened_stop)
                    risk = entry_max - stop_loss
                    nearest_resistance_rr = (resistance_levels[0] - entry_ref) / risk

                    if risk <= 0 or nearest_resistance_rr < Config.TP1_MIN_RR:
                        return None

            tp1 = self._pick_take_profit_level("LONG", entry_ref, risk, resistance_levels, Config.TP1_MIN_RR, tp1_rr)
            tp2 = self._pick_take_profit_level("LONG", entry_ref, risk, resistance_levels, tp1_rr + 0.25, tp2_rr)
            tp3 = self._pick_take_profit_level("LONG", entry_ref, risk, resistance_levels, tp2_rr + 0.25, tp3_rr)

            if not (tp1 < tp2 < tp3):
                tp1 = entry_ref + risk * tp1_rr
                tp2 = entry_ref + risk * tp2_rr
                tp3 = entry_ref + risk * tp3_rr

            rr = (tp1 - entry_ref) / risk

        else:
            anchor = max(close, ema20, ema50)
            entry_min = close * 0.999
            entry_max = min(
                anchor * 1.001,
                close + atr * Config.MAX_ENTRY_ZONE_ATR,
                close * (1 + Config.MAX_ENTRY_ZONE_PCT),
            )
            entry_ref = entry_min

            structure = self._recent_structure_levels(ltf_df, entry_ref, atr)
            stop_candidates = [close + atr * profile["max_stop_atr"], ema50 + stop_buffer]
            if pd.notna(resistance):
                stop_candidates.append(float(resistance) + stop_buffer)

            if structure["resistances"]:
                stop_candidates.append(min(structure["resistances"]) + stop_buffer)

            stop_candidates = [x for x in stop_candidates if x > entry_max]
            if not stop_candidates:
                stop_candidates = [entry_max + stop_buffer]

            stop_loss = min(stop_candidates)
            max_stop_distance = min(
                atr * profile["max_stop_atr"],
                entry_ref * profile["max_stop_pct"],
            )
            stop_loss = min(stop_loss, entry_ref + max_stop_distance)
            stop_loss = max(stop_loss, entry_max + stop_buffer)

            if stop_loss <= entry_max:
                return None

            risk = stop_loss - entry_min
            if risk <= 0:
                return None

            trend_strength = self._clamp((self._safe_float(last.get("adx")) - 14) / 26, 0.0, 1.0)
            tp1_rr = self._clamp(1.05 + trend_strength * 0.25, Config.TP1_MIN_RR, Config.TP1_MAX_RR)
            tp2_rr = self._clamp(tp1_rr + 0.48 + trend_strength * 0.18, 1.48, 1.95)
            tp3_rr = self._clamp(tp2_rr + 0.55 + trend_strength * 0.18, 2.05, Config.TP3_MAX_RR)

            support_levels = structure["supports"]

            if pd.notna(support):
                support_val = float(support)
                if support_val < entry_ref:
                    support_levels.append(support_val)

            support_levels = self._dedupe_levels(
                [x for x in support_levels if x < entry_ref],
                max(atr * 0.25, entry_ref * 0.001),
            )

            nearest_support_rr = None
            if support_levels:
                nearest_support_rr = (entry_ref - support_levels[-1]) / risk
                if nearest_support_rr < Config.TP1_MIN_RR:
                    target_distance = entry_ref - support_levels[-1]
                    desired_risk = target_distance / Config.TP1_MIN_RR
                    min_risk = entry_ref * 0.0025
                    min_stop_gap = max(stop_buffer * 0.25, entry_ref * 0.0005)
                    tightened_stop = max(entry_ref + desired_risk, entry_max + min_stop_gap)

                    if desired_risk < min_risk or tightened_stop <= entry_max:
                        return None

                    stop_loss = min(stop_loss, tightened_stop)
                    risk = stop_loss - entry_min
                    nearest_support_rr = (entry_ref - support_levels[-1]) / risk

                    if risk <= 0 or nearest_support_rr < Config.TP1_MIN_RR:
                        return None

            tp1 = self._pick_take_profit_level("SHORT", entry_ref, risk, support_levels, Config.TP1_MIN_RR, tp1_rr)
            tp2 = self._pick_take_profit_level("SHORT", entry_ref, risk, support_levels, tp1_rr + 0.25, tp2_rr)
            tp3 = self._pick_take_profit_level("SHORT", entry_ref, risk, support_levels, tp2_rr + 0.25, tp3_rr)

            if not (tp1 > tp2 > tp3):
                tp1 = entry_ref - risk * tp1_rr
                tp2 = entry_ref - risk * tp2_rr
                tp3 = entry_ref - risk * tp3_rr

            rr = (entry_ref - tp1) / risk

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
            "liquidity_profile": profile["liquidity"],
            "risk_pct": risk_pct,
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

    def _detect_regime_momentum_setup(
        self,
        htf_df: pd.DataFrame,
        mtf_df: pd.DataFrame,
        ltf_df: pd.DataFrame,
    ) -> SetupContext:
        if Config.STRATEGY_MODE == "SNIPER":
            return SetupContext("NONE", "NONE", "regime momentum fallback disabled in SNIPER")

        htf_last = self._closed(htf_df)
        mtf_last = self._closed(mtf_df)
        ltf_last = self._closed(ltf_df)
        ltf_prev = self._prev_closed(ltf_df)

        volume_ratio = self._safe_float(ltf_last.get("quote_volume_ratio"), 1.0)
        atr_ratio_value = self._safe_float(ltf_last.get("atr_ratio"))
        ltf_adx = self._safe_float(ltf_last.get("adx"))

        min_volume_ratio = Config.MIN_SETUP_VOLUME_RATIO
        if ltf_adx >= 24:
            min_volume_ratio = min(min_volume_ratio, 0.35)

        if volume_ratio < min_volume_ratio:
            return SetupContext("NONE", "NONE", "regime momentum fallback: слабый 15m volume")

        if atr_ratio_value < Config.MIN_SETUP_ATR_RATIO and ltf_adx < 22:
            return SetupContext("NONE", "NONE", "regime momentum fallback: слабый 15m ATR")

        htf_regime = self.regime_analyzer.detect_regime(htf_df)
        mtf_regime = self.regime_analyzer.detect_regime(mtf_df)

        long_score = (
            self.structure_engine._direction_score(htf_last, "LONG", Config.MIN_ADX_4H) * 1.15
            + self.structure_engine._direction_score(mtf_last, "LONG", Config.MIN_ADX_1H)
            + self.structure_engine._direction_score(ltf_last, "LONG", max(Config.MIN_ADX_1H - 2, 10))
        )
        short_score = (
            self.structure_engine._direction_score(htf_last, "SHORT", Config.MIN_ADX_4H) * 1.15
            + self.structure_engine._direction_score(mtf_last, "SHORT", Config.MIN_ADX_1H)
            + self.structure_engine._direction_score(ltf_last, "SHORT", max(Config.MIN_ADX_1H - 2, 10))
        )

        close = self._safe_float(ltf_last.get("close"))
        prev_close = self._safe_float(ltf_prev.get("close"))
        rsi = self._safe_float(ltf_last.get("rsi"), 50.0)
        macd_hist = self._safe_float(ltf_last.get("macd_hist"))
        prev_macd_hist = self._safe_float(ltf_prev.get("macd_hist"))

        long_momentum = (
            (close > prev_close or macd_hist > prev_macd_hist)
            and 42 <= rsi <= Config.LONG_MAX_RSI_ENTRY
        )
        short_momentum = (
            (close < prev_close or macd_hist < prev_macd_hist)
            and Config.SHORT_MIN_RSI_ENTRY <= rsi <= 58
        )

        htf_long_ok = htf_regime.direction in {"LONG", "NONE"} or htf_regime.is_volatility_expansion
        htf_short_ok = htf_regime.direction in {"SHORT", "NONE"} or htf_regime.is_volatility_expansion
        mtf_long_ok = mtf_regime.direction in {"LONG", "NONE"}
        mtf_short_ok = mtf_regime.direction in {"SHORT", "NONE"}

        min_score = 5.0
        min_edge = 0.25

        if htf_long_ok and mtf_long_ok and long_momentum and long_score >= min_score and long_score >= short_score + min_edge:
            return SetupContext(
                "MOMENTUM_CONTINUATION",
                "LONG",
                "fallback: regime/momentum setup LONG без классической swing-структуры",
            )

        if htf_short_ok and mtf_short_ok and short_momentum and short_score >= min_score and short_score >= long_score + min_edge:
            return SetupContext(
                "MOMENTUM_CONTINUATION",
                "SHORT",
                "fallback: regime/momentum setup SHORT без классической swing-структуры",
            )

        return SetupContext("NONE", "NONE", "regime momentum fallback не найден")

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
            fallback_setup = self._detect_regime_momentum_setup(htf_df, mtf_df, ltf_df)
            if fallback_setup.setup_type != "NONE":
                setup = fallback_setup

        if setup.setup_type == "NONE":
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason=setup.reason,
                diagnostics=diagnostics,
            )

        diagnostics["setup_type"] = setup.setup_type
        diagnostics["direction"] = setup.direction

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

        levels = self.build_trade_levels(symbol, setup.direction, ltf_df)
        if not levels:
            return SignalCheckResult(
                symbol=symbol,
                signal=None,
                skip_reason="не удалось построить entry/stop/tp",
                diagnostics=diagnostics,
            )

        diagnostics["rr"] = round(float(levels["rr"]), 3)
        diagnostics["score"] = round(float(score), 3)
        diagnostics["setup_type"] = setup.setup_type
        diagnostics["direction"] = setup.direction
        diagnostics["liquidity_profile"] = levels.get("liquidity_profile")
        diagnostics["risk_pct"] = round(float(levels.get("risk_pct", 0.0)), 5)

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
