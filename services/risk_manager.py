from dataclasses import dataclass
from typing import Optional


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


class RiskManager:
    def __init__(self):
        pass

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

        # фильтр хрупких сделок
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