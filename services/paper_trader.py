from dataclasses import dataclass
from typing import Optional

from services.db import db


@dataclass
class VirtualTrade:
    id: int | None
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
    status: str
    result_usdt: float = 0.0
    result_r: float = 0.0
    close_reason: Optional[str] = None


class PaperTrader:
    def _target_r(self, trade: dict, price: float) -> float:
        entry_price = float(trade["entry_price"])
        stop_loss = float(trade["stop_loss"])

        if trade["direction"] == "LONG":
            risk = entry_price - stop_loss
            if risk <= 0:
                return 0.0
            return (float(price) - entry_price) / risk

        risk = stop_loss - entry_price
        if risk <= 0:
            return 0.0
        return (entry_price - float(price)) / risk

    async def get_state(self) -> dict:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM paper_state WHERE id=1")
        return dict(row)

    async def open_trade(self, signal) -> Optional[VirtualTrade]:
        assert db.pool is not None

        async with db.pool.acquire() as conn:
            exists = await conn.fetchrow(
                """
                SELECT id FROM paper_trades
                WHERE symbol=$1 AND direction=$2 AND status='OPEN'
                LIMIT 1
                """,
                signal.symbol,
                signal.direction,
            )
            if exists:
                return None

            state = await conn.fetchrow("SELECT * FROM paper_state WHERE id=1")
            balance = float(state["balance"])
            risk_per_trade = float(state["risk_per_trade"])

            entry_price = (signal.entry_min + signal.entry_max) / 2.0
            risk_amount = balance * risk_per_trade
            risk_per_unit = abs(entry_price - signal.stop_loss)

            if risk_per_unit <= 0:
                return None

            size = risk_amount / risk_per_unit

            row = await conn.fetchrow(
                """
                INSERT INTO paper_trades (
                    symbol, direction, signal_type, entry_min, entry_max,
                    entry_price, stop_loss, tp1, tp2, tp3, size, risk_amount,
                    status
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'OPEN')
                RETURNING id
                """,
                signal.symbol,
                signal.direction,
                getattr(signal, "signal_type", "UNKNOWN"),
                signal.entry_min,
                signal.entry_max,
                entry_price,
                signal.stop_loss,
                signal.tp1,
                signal.tp2,
                signal.tp3,
                size,
                risk_amount,
            )

        return VirtualTrade(
            id=row["id"],
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

    async def update_symbol_price(self, symbol: str, high: float, low: float) -> list[VirtualTrade]:
        assert db.pool is not None
        closed_now: list[VirtualTrade] = []

        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM paper_trades WHERE symbol=$1 AND status='OPEN'",
                symbol,
            )

            state = await conn.fetchrow("SELECT * FROM paper_state WHERE id=1")
            balance = float(state["balance"])

            for row in rows:
                trade = dict(row)
                close_reason = None
                result_r = 0.0

                if trade["direction"] == "LONG":
                    if low <= trade["stop_loss"]:
                        close_reason = "STOP_HIT"
                        result_r = -1.0
                    elif high >= trade["tp3"]:
                        close_reason = "TP3_HIT"
                        result_r = self._target_r(trade, trade["tp3"])
                    elif high >= trade["tp2"]:
                        close_reason = "TP2_HIT"
                        result_r = self._target_r(trade, trade["tp2"])
                    elif high >= trade["tp1"]:
                        close_reason = "TP1_HIT"
                        result_r = self._target_r(trade, trade["tp1"])
                else:
                    if high >= trade["stop_loss"]:
                        close_reason = "STOP_HIT"
                        result_r = -1.0
                    elif low <= trade["tp3"]:
                        close_reason = "TP3_HIT"
                        result_r = self._target_r(trade, trade["tp3"])
                    elif low <= trade["tp2"]:
                        close_reason = "TP2_HIT"
                        result_r = self._target_r(trade, trade["tp2"])
                    elif low <= trade["tp1"]:
                        close_reason = "TP1_HIT"
                        result_r = self._target_r(trade, trade["tp1"])

                if close_reason:
                    result_r = round(result_r, 4)
                    result_usdt = round(float(trade["risk_amount"]) * result_r, 2)
                    balance = round(balance + result_usdt, 2)

                    await conn.execute(
                        """
                        UPDATE paper_trades
                        SET status='CLOSED',
                            result_usdt=$1,
                            result_r=$2,
                            close_reason=$3,
                            closed_at=NOW()
                        WHERE id=$4
                        """,
                        result_usdt,
                        result_r,
                        close_reason,
                        trade["id"],
                    )

                    closed_now.append(
                        VirtualTrade(
                            id=trade["id"],
                            symbol=trade["symbol"],
                            direction=trade["direction"],
                            signal_type=trade["signal_type"],
                            entry_min=trade["entry_min"],
                            entry_max=trade["entry_max"],
                            entry_price=trade["entry_price"],
                            stop_loss=trade["stop_loss"],
                            tp1=trade["tp1"],
                            tp2=trade["tp2"],
                            tp3=trade["tp3"],
                            size=trade["size"],
                            risk_amount=trade["risk_amount"],
                            status="CLOSED",
                            result_usdt=result_usdt,
                            result_r=result_r,
                            close_reason=close_reason,
                        )
                    )

            await conn.execute(
                "UPDATE paper_state SET balance=$1 WHERE id=1",
                balance,
            )

        return closed_now

    async def stats(self) -> dict:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            state = await conn.fetchrow("SELECT * FROM paper_state WHERE id=1")
            total = await conn.fetchval("SELECT COUNT(*) FROM paper_trades")
            open_trades = await conn.fetchval("SELECT COUNT(*) FROM paper_trades WHERE status='OPEN'")
            closed = await conn.fetchval("SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED'")
            wins = await conn.fetchval("SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED' AND result_usdt > 0")
            losses = await conn.fetchval("SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED' AND result_usdt < 0")
            total_r = await conn.fetchval("SELECT COALESCE(SUM(result_r), 0) FROM paper_trades WHERE status='CLOSED'")
            closed_rows = await conn.fetch(
                """
                SELECT result_usdt, result_r
                FROM paper_trades
                WHERE status='CLOSED'
                ORDER BY closed_at ASC NULLS LAST, id ASC
                """
            )
            open_risk = await conn.fetchval(
                """
                SELECT COALESCE(SUM(risk_amount), 0)
                FROM paper_trades
                WHERE status='OPEN'
                """
            )
            open_volume = await conn.fetchval(
                """
                SELECT COALESCE(SUM(size * entry_price), 0)
                FROM paper_trades
                WHERE status='OPEN'
                """
            )

        start_balance = float(state["start_balance"])
        balance = float(state["balance"])
        risk_per_trade = float(state["risk_per_trade"])
        pnl = round(balance - start_balance, 2)
        winrate = round((wins / closed) * 100, 2) if closed > 0 else 0.0
        result_r_values = [float(row["result_r"] or 0.0) for row in closed_rows]
        win_r_values = [x for x in result_r_values if x > 0]
        loss_r_values = [x for x in result_r_values if x < 0]
        gross_profit = sum(win_r_values)
        gross_loss = abs(sum(loss_r_values))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else ("∞" if gross_profit > 0 else 0.0)

        equity = 0.0
        peak = 0.0
        max_drawdown = 0.0

        for result_r in result_r_values:
            equity += result_r
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

        return {
            "start_balance": round(start_balance, 2),
            "balance": round(balance, 2),
            "risk_per_trade": risk_per_trade,
            "pnl_usdt": pnl,
            "total_r": round(float(total_r), 2),
            "total_trades": int(total),
            "open_trades": int(open_trades),
            "closed_trades": int(closed),
            "wins": int(wins),
            "losses": int(losses),
            "winrate": winrate,
            "profit_factor": round(profit_factor, 2) if isinstance(profit_factor, float) else profit_factor,
            "expectancy": round(sum(result_r_values) / int(closed), 4) if int(closed) > 0 else 0.0,
            "avg_win": round(sum(win_r_values) / len(win_r_values), 4) if win_r_values else 0.0,
            "avg_loss": round(sum(loss_r_values) / len(loss_r_values), 4) if loss_r_values else 0.0,
            "max_drawdown": round(max_drawdown, 4),
            "open_risk_usdt": round(float(open_risk or 0.0), 2),
            "open_volume_usdt": round(float(open_volume or 0.0), 2),
        }

    async def get_open_trades(self) -> list[dict]:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM paper_trades WHERE status='OPEN' ORDER BY created_at DESC"
            )
        return [dict(row) for row in rows]

    async def get_last_closed(self, limit: int = 10) -> list[dict]:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM paper_trades
                WHERE status='CLOSED'
                ORDER BY closed_at DESC NULLS LAST
                LIMIT $1
                """,
                limit,
            )
        return [dict(row) for row in rows]
