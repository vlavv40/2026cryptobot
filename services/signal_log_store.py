import json

from services.db import db


class SignalLogStore:
    async def add_signal(self, payload: dict):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO signal_logs (payload) VALUES ($1::jsonb)",
                json.dumps(payload, ensure_ascii=False),
            )

    async def get_last_signals(self, limit: int = 5) -> list[dict]:
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT payload
                FROM signal_logs
                ORDER BY id DESC
                LIMIT $1
                """,
                limit,
            )

        result = []
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            result.append(dict(payload))
        return result