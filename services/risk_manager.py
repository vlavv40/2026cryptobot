from dataclasses import dataclass
from typing import Optional

from config import Config


@dataclass
class RiskReport:
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    rr: float
    risk_pct: float
    valid: bool
    reason: str


@dataclass
class PositionReport:
    margin_usd: float
    leverage: float
    notional_usd: float
    size: float
    risk_usd: float
    risk_pct_from_deposit: float
    stop_distance_pct: float


class RiskManager:
    def calculate_fixed_position(self, entry: float, stop_loss: float, balance: float) -> Optional[PositionReport]:
        if entry <= 0 or stop_loss <= 0 or balance <= 0:
            return None

        margin_usd = float(getattr(Config, "PAPER_TRADE_MARGIN_USD", 100))
        leverage = float(getattr(Config, "PAPER_LEVERAGE", 5))

        notional_usd = margin_usd * leverage
        size = notional_usd / entry

        stop_distance_pct = abs(entry - stop_loss) / entry
        risk_usd = notional_usd * stop_distance_pct
        risk_pct_from_deposit = risk_usd / balance

        return PositionReport(
            margin_usd=round(margin_usd, 2),
            leverage=round(leverage, 2),
            notional_usd=round(notional_usd, 2),
            size=round(size, 8),
            risk_usd=round(risk_usd, 2),
            risk_pct_from_deposit=round(risk_pct_from_deposit, 4),
            stop_distance_pct=round(stop_distance_pct, 4),
        )

    def calculate_long(
        self,
        entry: float,
        swing_low: Optional[float],
        atr: float,
    ) -> RiskReport:
        if swing_low is None or atr <= 0:
            return RiskReport(0, 0, 0, 0, 0, 0, 0, False, "нет swing low или ATR")

        stop_loss = swing_low - atr * 0.2

        if stop_loss >= entry:
            return RiskReport(0, 0, 0, 0, 0, 0, 0, False, "некорректный стоп")

        risk = entry - stop_loss

        if risk <= 0:
            return RiskReport(0, 0, 0, 0, 0, 0, 0, False, "нулевой риск")

        tp1 = entry + risk * 1.8
        tp2 = entry + risk * 2.5
        tp3 = entry + risk * 3.2

        rr = (tp1 - entry) / risk
        risk_pct = risk / entry

        if risk_pct < 0.0025:
            return RiskReport(entry, stop_loss, tp1, tp2, tp3, rr, risk_pct, False, "слишком близкий стоп")

        if rr < 1.8:
            return RiskReport(entry, stop_loss, tp1, tp2, tp3, rr, risk_pct, False, "слабый RR")

        return RiskReport(entry, stop_loss, tp1, tp2, tp3, rr, risk_pct, True, "OK")

    def calculate_short(
        self,
        entry: float,
        swing_high: Optional[float],
        atr: float,
    ) -> RiskReport:
        if swing_high is None or atr <= 0:
            return RiskReport(0, 0, 0, 0, 0, 0, 0, False, "нет swing high или ATR")

        stop_loss = swing_high + atr * 0.2

        if stop_loss <= entry:
            return RiskReport(0, 0, 0, 0, 0, 0, 0, False, "некорректный стоп")

        risk = stop_loss - entry

        if risk <= 0:
            return RiskReport(0, 0, 0, 0, 0, 0, 0, False, "нулевой риск")

        tp1 = entry - risk * 1.8
        tp2 = entry - risk * 2.5
        tp3 = entry - risk * 3.2

        rr = (entry - tp1) / risk
        risk_pct = risk / entry

        if risk_pct < 0.0025:
            return RiskReport(entry, stop_loss, tp1, tp2, tp3, rr, risk_pct, False, "слишком близкий стоп")

        if rr < 1.8:
            return RiskReport(entry, stop_loss, tp1, tp2, tp3, rr, risk_pct, False, "слабый RR")

        return RiskReport(entry, stop_loss, tp1, tp2, tp3, rr, risk_pct, True, "OK")