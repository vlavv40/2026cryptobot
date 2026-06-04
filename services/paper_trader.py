from dataclasses import dataclass
from typing import Optional

from config import Config
from services.db import db
from services.stats_window import stats_start_at


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
    active_stop_loss: Optional[float] = None
    protection_stage: str = "INITIAL"


class PaperTrader:
    TP1_SHARE = 0.70
    TP2_SHARE = 0.20
    TP3_SHARE = 0.10

    def _trade_margin_usdt(self) -> float:
        return float(Config.AUTO_TRADE_USDT)

    def _position_usdt(self) -> float:
        return self._trade_margin_usdt() * float(Config.AUTO_TRADE_LEVERAGE)

    def _position_size(self, entry_price: float) -> float:
        entry_price = float(entry_price)
        if entry_price <= 0:
            return 0.0
        return self._position_usdt() / entry_price

    def _initial_risk_amount(self, trade: dict) -> float:
        entry_price = float(trade["entry_price"])
        stop_loss = float(trade["stop_loss"])
        size = self._position_size(entry_price)
        if size <= 0:
            return float(trade.get("risk_amount") or 0.0)
        return abs(entry_price - stop_loss) * size

    def _fixed_result_usdt(self, trade: dict) -> float:
        return round(self._initial_risk_amount(trade) * float(trade.get("result_r") or 0.0), 2)

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

    def _stage(self, trade: dict) -> str:
        return trade.get("protection_stage") or "INITIAL"

    def _remaining_share(self, trade: dict) -> float:
        stage = self._stage(trade)

        if stage == "TP2_HIT":
            return self.TP3_SHARE

        if stage == "TP1_HIT":
            return self.TP2_SHARE + self.TP3_SHARE

        return 1.0

    def _weighted_result_r(self, trade: dict, close_reason: str) -> float:
        tp1_r = self._target_r(trade, trade["tp1"])
        tp2_r = self._target_r(trade, trade["tp2"])
        tp3_r = self._target_r(trade, trade["tp3"])
        stage = self._stage(trade)

        if close_reason == "TP3_HIT":
            return round(
                self.TP1_SHARE * tp1_r
                + self.TP2_SHARE * tp2_r
                + self.TP3_SHARE * tp3_r,
                4,
            )

        stop_price = float(trade.get("active_stop_loss") or trade["stop_loss"])
        stop_r = self._target_r(trade, stop_price)

        if stage == "TP2_HIT":
            return round(
                self.TP1_SHARE * tp1_r
                + self.TP2_SHARE * tp2_r
                + self.TP3_SHARE * stop_r,
                4,
            )

        if stage == "TP1_HIT":
            return round(
                self.TP1_SHARE * tp1_r
                + (self.TP2_SHARE + self.TP3_SHARE) * stop_r,
                4,
            )

        return round(stop_r, 4)

    def _detect_event(self, trade: dict, high: float, low: float) -> str | None:
        stage = self._stage(trade)
        stop_loss = float(trade.get("active_stop_loss") or trade["stop_loss"])

        if trade["direction"] == "LONG":
            if low <= stop_loss:
                return "STOP_HIT"
            if high >= trade["tp3"]:
                return "TP3_HIT"
            if stage != "TP2_HIT" and high >= trade["tp2"]:
                return "TP2_HIT"
            if stage == "INITIAL" and high >= trade["tp1"]:
                return "TP1_HIT"
            return None

        if high >= stop_loss:
            return "STOP_HIT"
        if low <= trade["tp3"]:
            return "TP3_HIT"
        if stage != "TP2_HIT" and low <= trade["tp2"]:
            return "TP2_HIT"
        if stage == "INITIAL" and low <= trade["tp1"]:
            return "TP1_HIT"

        return None

    def _open_risk_amount(self, trade: dict) -> float:
        stop_price = float(trade.get("active_stop_loss") or trade["stop_loss"])
        stop_r = self._target_r(trade, stop_price)
        downside_r = abs(min(stop_r, 0.0))
        return self._initial_risk_amount(trade) * self._remaining_share(trade) * downside_r

    def _open_volume_usdt(self, trade: dict) -> float:
        return self._position_usdt() * self._remaining_share(trade)

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

            entry_price = (signal.entry_min + signal.entry_max) / 2.0
            risk_per_unit = abs(entry_price - signal.stop_loss)
            size = self._position_size(entry_price)

            if risk_per_unit <= 0 or size <= 0:
                return None

            risk_amount = risk_per_unit * size

            row = await conn.fetchrow(
                """
                INSERT INTO paper_trades (
                    symbol, direction, signal_type, entry_min, entry_max,
                    entry_price, stop_loss, tp1, tp2, tp3, size, risk_amount,
                    status, active_stop_loss, protection_stage
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,'OPEN',$7,'INITIAL')
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
            active_stop_loss=signal.stop_loss,
            protection_stage="INITIAL",
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
                event = self._detect_event(trade, high, low)

                if not event:
                    continue

                if event == "TP1_HIT":
                    await conn.execute(
                        """
                        UPDATE paper_trades
                        SET active_stop_loss=$1,
                            protection_stage='TP1_HIT',
                            tp1_hit_at=COALESCE(tp1_hit_at, NOW()),
                            protection_updated_at=NOW()
                        WHERE id=$2
                          AND status='OPEN'
                          AND protection_stage='INITIAL'
                        """,
                        trade["entry_price"],
                        trade["id"],
                    )
                    continue

                if event == "TP2_HIT":
                    await conn.execute(
                        """
                        UPDATE paper_trades
                        SET active_stop_loss=$1,
                            protection_stage='TP2_HIT',
                            tp1_hit_at=COALESCE(tp1_hit_at, NOW()),
                            tp2_hit_at=COALESCE(tp2_hit_at, NOW()),
                            protection_updated_at=NOW()
                        WHERE id=$2
                          AND status='OPEN'
                          AND protection_stage <> 'TP2_HIT'
                        """,
                        trade["tp1"],
                        trade["id"],
                    )
                    continue

                close_reason = event
                result_r = self._weighted_result_r(trade, close_reason)
                trade_risk_amount = self._initial_risk_amount(trade)
                result_usdt = round(trade_risk_amount * result_r, 2)
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
                        risk_amount=trade_risk_amount,
                        status="CLOSED",
                        result_usdt=result_usdt,
                        result_r=result_r,
                        close_reason=close_reason,
                        active_stop_loss=trade.get("active_stop_loss"),
                        protection_stage=self._stage(trade),
                    )
                )

            await conn.execute(
                "UPDATE paper_state SET balance=$1 WHERE id=1",
                balance,
            )

        return closed_now

    async def stats(self) -> dict:
        assert db.pool is not None
        start_at = stats_start_at()

        async with db.pool.acquire() as conn:
            state = await conn.fetchrow("SELECT * FROM paper_state WHERE id=1")
            open_trades = await conn.fetchval("SELECT COUNT(*) FROM paper_trades WHERE status='OPEN'")
            if start_at:
                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM paper_trades WHERE created_at >= $1 OR status='OPEN'",
                    start_at,
                )
                closed = await conn.fetchval(
                    "SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED' AND created_at >= $1",
                    start_at,
                )
                wins = await conn.fetchval(
                    "SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED' AND result_r > 0 AND created_at >= $1",
                    start_at,
                )
                losses = await conn.fetchval(
                    "SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED' AND result_r < 0 AND created_at >= $1",
                    start_at,
                )
                total_r = await conn.fetchval(
                    "SELECT COALESCE(SUM(result_r), 0) FROM paper_trades WHERE status='CLOSED' AND created_at >= $1",
                    start_at,
                )
                closed_rows = await conn.fetch(
                    """
                    SELECT result_usdt, result_r, entry_price, stop_loss, risk_amount
                    FROM paper_trades
                    WHERE status='CLOSED' AND created_at >= $1
                    ORDER BY closed_at ASC NULLS LAST, id ASC
                    """,
                    start_at,
                )
            else:
                total = await conn.fetchval("SELECT COUNT(*) FROM paper_trades")
                closed = await conn.fetchval("SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED'")
                wins = await conn.fetchval("SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED' AND result_r > 0")
                losses = await conn.fetchval("SELECT COUNT(*) FROM paper_trades WHERE status='CLOSED' AND result_r < 0")
                total_r = await conn.fetchval("SELECT COALESCE(SUM(result_r), 0) FROM paper_trades WHERE status='CLOSED'")
                closed_rows = await conn.fetch(
                    """
                    SELECT result_usdt, result_r, entry_price, stop_loss, risk_amount
                    FROM paper_trades
                    WHERE status='CLOSED'
                    ORDER BY closed_at ASC NULLS LAST, id ASC
                    """
                )
            open_rows = await conn.fetch(
                "SELECT * FROM paper_trades WHERE status='OPEN'"
            )

        start_balance = float(state["start_balance"])
        stored_balance = float(state["balance"])
        risk_per_trade = float(state["risk_per_trade"])
        closed_trade_rows = [dict(row) for row in closed_rows]
        result_usdt_values = [self._fixed_result_usdt(row) for row in closed_trade_rows]
        pnl = round(sum(result_usdt_values), 2)
        balance = round(start_balance + pnl, 2)
        winrate = round((wins / closed) * 100, 2) if closed > 0 else 0.0
        result_r_values = [float(row["result_r"] or 0.0) for row in closed_trade_rows]
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

        open_risk = sum(self._open_risk_amount(dict(row)) for row in open_rows)
        open_volume = sum(self._open_volume_usdt(dict(row)) for row in open_rows)
        protected_trades = sum(
            1
            for row in open_rows
            if self._stage(dict(row)) in {"TP1_HIT", "TP2_HIT"}
        )

        return {
            "start_balance": round(start_balance, 2),
            "balance": round(balance, 2),
            "stored_balance": round(stored_balance, 2),
            "risk_per_trade": risk_per_trade,
            "trade_margin_usdt": round(self._trade_margin_usdt(), 2),
            "trade_leverage": int(Config.AUTO_TRADE_LEVERAGE),
            "trade_position_usdt": round(self._position_usdt(), 2),
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
            "protected_trades": protected_trades,
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
