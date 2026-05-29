# services/trade_tracker.py

import csv
import json
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd

from config import Config
from services.db import db
from services.stats_analyzer import StatsAnalyzer


class TradeTracker:
    TP1_SHARE = 0.70
    TP2_SHARE = 0.20
    TP3_SHARE = 0.10

    def _target_r(self, item: dict, price: float) -> float:
        entry_min = float(item["entry_min"])
        entry_max = float(item["entry_max"])
        stop_loss = float(item["stop_loss"])

        entry_mid = float(item.get("entry_price") or ((entry_min + entry_max) / 2.0))
        direction = item["direction"]

        if direction == "LONG":
            risk = entry_mid - stop_loss
            if risk <= 0:
                return 0.0
            return (float(price) - entry_mid) / risk

        risk = stop_loss - entry_mid
        if risk <= 0:
            return 0.0
        return (entry_mid - float(price)) / risk

    async def _calculate_realized_r(self, item: dict, status: str) -> float:
        tp1 = float(item["tp1"])
        tp2 = float(item["tp2"])
        tp3 = float(item["tp3"])

        tp1_r = self._target_r(item, tp1)
        tp2_r = self._target_r(item, tp2)
        tp3_r = self._target_r(item, tp3)

        tp1_hit = bool(item.get("tp1_hit_at"))
        tp2_hit = bool(item.get("tp2_hit_at"))

        if status == "STOP_HIT":
            stop_price = float(item.get("active_stop_loss") or item["stop_loss"])
            stop_r = self._target_r(item, stop_price)

            if tp2_hit:
                return round(
                    self.TP1_SHARE * tp1_r
                    + self.TP2_SHARE * tp2_r
                    + self.TP3_SHARE * stop_r,
                    4,
                )

            if tp1_hit:
                return round(
                    self.TP1_SHARE * tp1_r
                    + (self.TP2_SHARE + self.TP3_SHARE) * stop_r,
                    4,
                )

            return round(stop_r, 4)

        if status == "TP1_HIT":
            return round(tp1_r, 4)

        if status == "TP2_HIT":
            return round(
                self.TP1_SHARE * tp1_r
                + (self.TP2_SHARE + self.TP3_SHARE) * tp2_r,
                4,
            )

        if status == "TP3_HIT":
            return round(
                self.TP1_SHARE * tp1_r
                + self.TP2_SHARE * tp2_r
                + self.TP3_SHARE * tp3_r,
                4,
            )

        return 0.0

    async def add_signal(self, payload: dict):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tracked_signals (
                    id, symbol, direction, entry_min, entry_max, stop_loss,
                    tp1, tp2, tp3, score, status, realized_r,
                    created_at, closed_at, notified, active_stop_loss,
                    protection_stage, entry_price, initial_position_qty,
                    tp1_qty, tp2_qty, tp3_qty
                )
                VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                    'OPEN',NULL,$11,NULL,FALSE,$6,'INITIAL',
                    $12,$13,$14,$15,$16
                )
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
                payload.get("entry_price"),
                payload.get("initial_position_qty"),
                payload.get("tp1_qty"),
                payload.get("tp2_qty"),
                payload.get("tp3_qty"),
            )

    async def get_open_signals(self) -> list[dict]:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM tracked_signals WHERE status='OPEN' ORDER BY created_at DESC"
            )
        return [dict(row) for row in rows]

    async def _stats_reset_at(self):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            value = await conn.fetchval(
                "SELECT value FROM strategy_parameters WHERE key='statistics_reset_at'"
            )

        if not value:
            return None

        try:
            if isinstance(value, str):
                value = json.loads(value)
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    async def get_all_signals(self, include_before_reset: bool = False) -> list[dict]:
        assert db.pool is not None
        reset_at = None if include_before_reset else await self._stats_reset_at()

        async with db.pool.acquire() as conn:
            if reset_at:
                rows = await conn.fetch(
                    """
                    SELECT * FROM tracked_signals
                    WHERE created_at >= $1
                    ORDER BY created_at DESC
                    """,
                    reset_at,
                )
            else:
                rows = await conn.fetch("SELECT * FROM tracked_signals ORDER BY created_at DESC")
        return [dict(row) for row in rows]

    async def mark_target_hit(self, target_id: str, target_status: str, new_stop_loss: float):
        all_signals = await self.get_all_signals(include_before_reset=True)
        current = next((x for x in all_signals if x["id"] == target_id and x["status"] == "OPEN"), None)
        if not current:
            return None

        now = datetime.utcnow()

        assert db.pool is not None
        async with db.pool.acquire() as conn:
            if target_status == "TP1_HIT":
                row = await conn.fetchrow(
                    """
                    UPDATE tracked_signals
                    SET tp1_hit_at=COALESCE(tp1_hit_at, $1),
                        active_stop_loss=$2,
                        protection_stage='TP1_HIT',
                        protection_updated_at=$1
                    WHERE id=$3
                      AND status='OPEN'
                      AND protection_stage='INITIAL'
                    RETURNING *
                    """,
                    now,
                    new_stop_loss,
                    target_id,
                )
            elif target_status == "TP2_HIT":
                row = await conn.fetchrow(
                    """
                    UPDATE tracked_signals
                    SET tp1_hit_at=COALESCE(tp1_hit_at, $1),
                        tp2_hit_at=COALESCE(tp2_hit_at, $1),
                        active_stop_loss=$2,
                        protection_stage='TP2_HIT',
                        protection_updated_at=$1
                    WHERE id=$3
                      AND status='OPEN'
                      AND protection_stage <> 'TP2_HIT'
                    RETURNING *
                    """,
                    now,
                    new_stop_loss,
                    target_id,
                )
            else:
                return None

        return dict(row) if row else None

    async def update_signal(self, target_id: str, new_status: str):
        all_signals = await self.get_all_signals(include_before_reset=True)
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
        await self.record_equity_snapshot("signals", {"last_signal_id": target_id, "status": new_status})
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

    async def get_equity_curve(self) -> list[dict]:
        analyzer = StatsAnalyzer(await self.get_all_signals())
        return analyzer.equity_curve()

    async def record_equity_snapshot(self, source: str, payload: dict | None = None):
        payload = payload or {}
        stats = await self.get_stats()

        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO equity_history (source, equity_r, payload, snapshot_at)
                VALUES ($1, $2, $3::jsonb, NOW())
                """,
                source,
                float(stats.get("total_r") or 0.0),
                json.dumps(payload),
            )

    async def refresh_symbol_whitelist(self) -> list[dict]:
        rows = await self.get_best_pairs(
            min_closed=Config.AUTO_WHITELIST_MIN_CLOSED_TRADES,
            limit=Config.AUTO_WHITELIST_SIZE,
        )
        rows = [
            item
            for item in rows
            if float(item.get("expectancy") or 0.0) >= Config.AUTO_WHITELIST_MIN_EXPECTANCY
        ]

        assert db.pool is not None
        async with db.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("TRUNCATE symbol_whitelist;")

                for item in rows:
                    await conn.execute(
                        """
                        INSERT INTO symbol_whitelist (
                            symbol, expectancy, winrate, total_r,
                            closed_count, refreshed_at
                        )
                        VALUES ($1,$2,$3,$4,$5,NOW())
                        ON CONFLICT (symbol)
                        DO UPDATE SET
                            expectancy=EXCLUDED.expectancy,
                            winrate=EXCLUDED.winrate,
                            total_r=EXCLUDED.total_r,
                            closed_count=EXCLUDED.closed_count,
                            refreshed_at=NOW()
                        """,
                        item["symbol"],
                        float(item.get("expectancy") or 0.0),
                        float(item.get("winrate") or 0.0),
                        float(item.get("total_r") or 0.0),
                        int(item.get("closed") or 0),
                    )
                    await conn.execute(
                        """
                        INSERT INTO symbol_stats_snapshots (symbol, payload, snapshot_at)
                        VALUES ($1, $2::jsonb, NOW())
                        """,
                        item["symbol"],
                        json.dumps(item),
                    )

        return rows

    async def get_symbol_whitelist(self) -> list[dict]:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM symbol_whitelist
                ORDER BY expectancy DESC, winrate DESC, closed_count DESC
                """
            )
        return [dict(row) for row in rows]

    async def whitelist_is_stale(self) -> bool:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            refreshed_at = await conn.fetchval("SELECT MAX(refreshed_at) FROM symbol_whitelist")

        if not refreshed_at:
            return True

        return refreshed_at <= datetime.utcnow() - timedelta(hours=Config.AUTO_WHITELIST_REFRESH_HOURS)

    async def reset_stats(self):
        await db.reset_stats()

    async def reset_db(self):
        await db.reset_db()

    async def get_json_path(self) -> str:
        return "tracked_signals.json"

    async def get_csv_path(self) -> str:
        return "tracked_signals.csv"

    async def export_csv(self) -> str:
        signals = await self.get_all_signals()

        path = Path("/tmp/trades_export.csv")

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow([
                "symbol",
                "direction",
                "entry_min",
                "entry_max",
                "stop_loss",
                "tp1",
                "tp2",
                "tp3",
                "status",
                "realized_r",
                "created_at",
                "closed_at",
            ])

            for s in signals:
                writer.writerow([
                    s["symbol"],
                    s["direction"],
                    s["entry_min"],
                    s["entry_max"],
                    s["stop_loss"],
                    s["tp1"],
                    s["tp2"],
                    s["tp3"],
                    s["status"],
                    s.get("realized_r"),
                    s["created_at"],
                    s["closed_at"],
                ])

        return str(path)

    async def export_excel(self) -> str:
        signals = await self.get_all_signals()
        stats = await self.get_stats()
        pair_stats = await self.get_pair_stats()
        side_stats = await self.get_side_stats()
        equity_curve = await self.get_equity_curve()

        path = Path("/tmp/trades_export.xlsx")

        df_signals = pd.DataFrame(signals)
        df_symbols = pd.DataFrame(pair_stats)
        df_equity = pd.DataFrame(equity_curve)
        df_overall = pd.DataFrame([stats])
        df_sides = pd.DataFrame(
            [
                {"side": side, **values}
                for side, values in side_stats.items()
            ]
        )

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df_overall.to_excel(writer, index=False, sheet_name="Overall")
            df_sides.to_excel(writer, index=False, sheet_name="LongShort")
            df_symbols.to_excel(writer, index=False, sheet_name="Symbols")
            df_equity.to_excel(writer, index=False, sheet_name="Equity")
            df_signals.to_excel(writer, index=False, sheet_name="Signals")

        return str(path)
