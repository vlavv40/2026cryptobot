from datetime import datetime

from services.db import db
from services.stats_analyzer import StatsAnalyzer


class TradeTracker:
    async def _calculate_realized_r(self, item: dict, status: str) -> float:
        entry_min = float(item["entry_min"])
        entry_max = float(item["entry_max"])
        stop_loss = float(item["stop_loss"])
        tp1 = float(item["tp1"])
        tp2 = float(item["tp2"])
        tp3 = float(item["tp3"])

        entry_mid = (entry_min + entry_max) / 2.0
        direction = item["direction"]

        if direction == "LONG":
            risk = entry_mid - stop_loss
            if risk <= 0:
                return 0.0
            if status == "STOP_HIT":
                return -1.0
            if status == "TP1_HIT":
                return round((tp1 - entry_mid) / risk, 4)
            if status == "TP2_HIT":
                return round((tp2 - entry_mid) / risk, 4)
            if status == "TP3_HIT":
                return round((tp3 - entry_mid) / risk, 4)
        else:
            risk = stop_loss - entry_mid
            if risk <= 0:
                return 0.0
            if status == "STOP_HIT":
                return -1.0
            if status == "TP1_HIT":
                return round((entry_mid - tp1) / risk, 4)
            if status == "TP2_HIT":
                return round((entry_mid - tp2) / risk, 4)
            if status == "TP3_HIT":
                return round((entry_mid - tp3) / risk, 4)

        return 0.0

    async def add_signal(self, payload: dict):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tracked_signals (
                    id, symbol, direction, entry_min, entry_max, stop_loss,
                    tp1, tp2, tp3, score, status, realized_r,
                    created_at, closed_at, notified
                )
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'OPEN',NULL,$11,NULL,FALSE)
                """,
                payload["id"],
                payload["symbol"],
                payload["direction"],
                payload["entry_min"],
                payload["entry_max"],
                payload["stop_loss"],
                payload["tp1"],
                payload["tp2"],
                payload["tp3"],
                payload["score"],
                datetime.utcnow(),
            )

    async def get_open_signals(self) -> list[dict]:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM tracked_signals WHERE status='OPEN' ORDER BY created_at DESC"
            )
        return [dict(row) for row in rows]

    async def get_all_signals(self) -> list[dict]:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM tracked_signals ORDER BY created_at DESC")
        return [dict(row) for row in rows]

    async def update_signal(self, target_id: str, new_status: str):
        all_signals = await self.get_all_signals()
        current = next((x for x in all_signals if x["id"] == target_id and x["status"] == "OPEN"), None)
        if not current:
            return None

        realized_r = await self._calculate_realized_r(current, new_status)

        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE tracked_signals
                SET status=$1, closed_at=$2, realized_r=$3, notified=FALSE
                WHERE id=$4
                """,
                new_status,
                datetime.utcnow(),
                realized_r,
                target_id,
            )

        current["status"] = new_status
        current["closed_at"] = datetime.utcnow()
        current["realized_r"] = realized_r
        current["notified"] = False
        return current

    async def mark_notified(self, target_id: str):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await conn.execute(
                "UPDATE tracked_signals SET notified=TRUE WHERE id=$1",
                target_id,
            )

    async def get_unnotified_closed_signals(self) -> list[dict]:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM tracked_signals
                WHERE status != 'OPEN' AND notified = FALSE
                ORDER BY closed_at DESC
                """
            )
        return [dict(row) for row in rows]

    async def get_stats(self) -> dict:
        analyzer = StatsAnalyzer(await self.get_all_signals())
        return analyzer.overall_stats()

    async def get_pair_stats(self) -> list[dict]:
        analyzer = StatsAnalyzer(await self.get_all_signals())
        return analyzer.pair_stats()

    async def get_best_pairs(self, min_closed: int = 1, limit: int = 5) -> list[dict]:
        analyzer = StatsAnalyzer(await self.get_all_signals())
        return analyzer.best_pairs(min_closed=min_closed, limit=limit)

    async def get_side_stats(self) -> dict:
        analyzer = StatsAnalyzer(await self.get_all_signals())
        return analyzer.side_stats()

    async def get_daily_report(self) -> list[dict]:
        analyzer = StatsAnalyzer(await self.get_all_signals())
        return analyzer.grouped_by_day()

    async def get_weekly_report(self) -> list[dict]:
        analyzer = StatsAnalyzer(await self.get_all_signals())
        return analyzer.grouped_by_week()

    async def get_json_path(self) -> str:
        return "tracked_signals.json"

    async def get_csv_path(self) -> str:
        return "tracked_signals.csv"