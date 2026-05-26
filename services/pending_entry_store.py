import json
from datetime import datetime, timedelta

from services.db import db
from services.signal_engine import Signal


class PendingEntryStore:
    def _key(self, symbol: str, direction: str) -> str:
        return f"{symbol}:{direction}"

    def _signal_payload(self, signal: Signal) -> dict:
        return {
            "symbol": signal.symbol,
            "direction": signal.direction,
            "entry_min": signal.entry_min,
            "entry_max": signal.entry_max,
            "stop_loss": signal.stop_loss,
            "tp1": signal.tp1,
            "tp2": signal.tp2,
            "tp3": signal.tp3,
            "score": signal.score,
            "reasons": signal.reasons,
            "diagnostics": signal.diagnostics,
            "signal_type": signal.signal_type,
        }

    def signal_from_payload(self, payload: dict) -> Signal:
        return Signal(
            symbol=payload["symbol"],
            direction=payload["direction"],
            entry_min=float(payload["entry_min"]),
            entry_max=float(payload["entry_max"]),
            stop_loss=float(payload["stop_loss"]),
            tp1=float(payload["tp1"]),
            tp2=float(payload["tp2"]),
            tp3=float(payload["tp3"]),
            score=float(payload["score"]),
            reasons=list(payload.get("reasons", [])),
            diagnostics=dict(payload.get("diagnostics", {})),
            signal_type=payload.get("signal_type", "SETUP"),
        )

    async def upsert_waiting(self, signal: Signal, wait_minutes: int, reason: str):
        assert db.pool is not None

        key = self._key(signal.symbol, signal.direction)
        now = datetime.utcnow()
        expires_at = now + timedelta(minutes=wait_minutes)
        payload = json.dumps(self._signal_payload(signal), ensure_ascii=False)

        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO pending_entries (
                    key, symbol, direction, payload, status, reason,
                    created_at, expires_at, last_checked_at, opened_at
                )
                VALUES ($1,$2,$3,$4::jsonb,'WAITING',$5,$6,$7,NULL,NULL)
                ON CONFLICT (key)
                DO UPDATE SET
                    payload=EXCLUDED.payload,
                    status='WAITING',
                    reason=EXCLUDED.reason,
                    created_at=EXCLUDED.created_at,
                    expires_at=EXCLUDED.expires_at,
                    last_checked_at=NULL,
                    opened_at=NULL
                """,
                key,
                signal.symbol,
                signal.direction,
                payload,
                reason,
                now,
                expires_at,
            )

    async def get_waiting(self) -> list[dict]:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM pending_entries
                WHERE status='WAITING'
                ORDER BY created_at ASC
                """
            )

        result = []
        for row in rows:
            item = dict(row)
            payload = item["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            item["payload"] = dict(payload)
            return_signal = self.signal_from_payload(item["payload"])
            item["signal"] = return_signal
            result.append(item)

        return result

    async def touch_checked(self, key: str):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE pending_entries
                SET last_checked_at=$1
                WHERE key=$2
                """,
                datetime.utcnow(),
                key,
            )

    async def mark_opened(self, key: str):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE pending_entries
                SET status='OPENED', opened_at=$1, last_checked_at=$1
                WHERE key=$2
                """,
                datetime.utcnow(),
                key,
            )

    async def mark_expired(self, key: str):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE pending_entries
                SET status='EXPIRED', last_checked_at=$1
                WHERE key=$2
                """,
                datetime.utcnow(),
                key,
            )
