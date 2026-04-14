from dataclasses import dataclass
from typing import List, Optional


@dataclass
class VirtualTrade:
    symbol: str
    direction: str
    signal_type: str
    entry_min: float
    entry_max: float
    entry_price: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    size: float
    risk_amount: float
    status: str  # OPEN / CLOSED
    result_usdt: float = 0.0
    result_r: float = 0.0
    close_reason: Optional[str] = None


class PaperTrader:
    def __init__(self, start_balance: float = 10000.0, risk_per_trade: float = 0.01):
        self.start_balance = start_balance
        self.balance = start_balance
        self.risk_per_trade = risk_per_trade
        self.trades: List[VirtualTrade] = []

    def _calc_entry_price(self, entry_min: float, entry_max: float) -> float:
        return (entry_min + entry_max) / 2.0

    def _calc_size(self, entry_price: float, stop_loss: float, risk_amount: float) -> float:
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit <= 0:
            return 0.0
        return risk_amount / risk_per_unit

    def has_open_trade(self, symbol: str, direction: str) -> bool:
        for trade in self.trades:
            if trade.symbol == symbol and trade.direction == direction and trade.status == "OPEN":
                return True
        return False

    def open_trade(self, signal) -> Optional[VirtualTrade]:
        if self.has_open_trade(signal.symbol, signal.direction):
            return None

        entry_price = self._calc_entry_price(signal.entry_min, signal.entry_max)
        risk_amount = self.balance * self.risk_per_trade
        size = self._calc_size(entry_price, signal.stop_loss, risk_amount)

        if size <= 0:
            return None

        trade = VirtualTrade(
            symbol=signal.symbol,
            direction=signal.direction,
            signal_type=getattr(signal, "signal_type", "UNKNOWN"),
            entry_min=signal.entry_min,
            entry_max=signal.entry_max,
            entry_price=entry_price,
            stop_loss=signal.stop_loss,
            tp1=signal.tp1,
            tp2=signal.tp2,
            tp3=signal.tp3,
            size=size,
            risk_amount=risk_amount,
            status="OPEN",
        )
        self.trades.append(trade)
        return trade

    def update_symbol_price(self, symbol: str, high: float, low: float) -> List[VirtualTrade]:
        closed_now: List[VirtualTrade] = []

        for trade in self.trades:
            if trade.symbol != symbol or trade.status != "OPEN":
                continue

            close_reason = None
            result_r = 0.0

            if trade.direction == "LONG":
                if low <= trade.stop_loss:
                    close_reason = "STOP_HIT"
                    result_r = -1.0
                elif high >= trade.tp3:
                    close_reason = "TP3_HIT"
                    result_r = 3.0
                elif high >= trade.tp2:
                    close_reason = "TP2_HIT"
                    result_r = 2.3
                elif high >= trade.tp1:
                    close_reason = "TP1_HIT"
                    result_r = 1.6

            elif trade.direction == "SHORT":
                if high >= trade.stop_loss:
                    close_reason = "STOP_HIT"
                    result_r = -1.0
                elif low <= trade.tp3:
                    close_reason = "TP3_HIT"
                    result_r = 3.0
                elif low <= trade.tp2:
                    close_reason = "TP2_HIT"
                    result_r = 2.3
                elif low <= trade.tp1:
                    close_reason = "TP1_HIT"
                    result_r = 1.6

            if close_reason:
                trade.status = "CLOSED"
                trade.close_reason = close_reason
                trade.result_r = result_r
                trade.result_usdt = round(trade.risk_amount * result_r, 2)
                self.balance = round(self.balance + trade.result_usdt, 2)
                closed_now.append(trade)

        return closed_now

    def stats(self) -> dict:
        total = len(self.trades)
        open_trades = len([t for t in self.trades if t.status == "OPEN"])
        closed = len([t for t in self.trades if t.status == "CLOSED"])
        wins = len([t for t in self.trades if t.status == "CLOSED" and t.result_usdt > 0])
        losses = len([t for t in self.trades if t.status == "CLOSED" and t.result_usdt < 0])

        total_pnl = round(self.balance - self.start_balance, 2)
        total_r = round(sum(t.result_r for t in self.trades if t.status == "CLOSED"), 2)
        winrate = round((wins / closed) * 100, 2) if closed > 0 else 0.0

        return {
            "start_balance": round(self.start_balance, 2),
            "balance": round(self.balance, 2),
            "pnl_usdt": total_pnl,
            "total_r": total_r,
            "total_trades": total,
            "open_trades": open_trades,
            "closed_trades": closed,
            "wins": wins,
            "losses": losses,
            "winrate": winrate,
        }