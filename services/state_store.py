import json
from datetime import datetime, timedelta

from services.db import db


class StateStore:
    def __init__(self, _unused_path: str | None = None):
        pass

    async def get_cooldown(self, key: str):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT expires_at FROM bot_state_cooldowns WHERE key=$1",
                key,
            )
            if not row:
                return None

            expires_at = row["expires_at"]
            if expires_at <= datetime.utcnow():
                await conn.execute("DELETE FROM bot_state_cooldowns WHERE key=$1", key)
                return None

            return expires_at

    async def set_cooldown(self, key: str, minutes: int):
        assert db.pool is not None
        expires_at = datetime.utcnow() + timedelta(minutes=minutes)

        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_state_cooldowns (key, expires_at)
                VALUES ($1, $2)
                ON CONFLICT (key)
                DO UPDATE SET expires_at=EXCLUDED.expires_at
                """,
                key,
                expires_at,
            )

    async def get_last_signal(self, key: str):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM bot_state_last_signals WHERE key=$1",
                key,
            )
            if not row:
                return None
            payload = row["payload"]
            if isinstance(payload, str):
                return json.loads(payload)
            return dict(payload)

    async def set_last_signal(self, key: str, payload: dict):
        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO bot_state_last_signals (key, payload)
                VALUES ($1, $2::jsonb)
                ON CONFLICT (key)
                DO UPDATE SET payload=EXCLUDED.payload, saved_at=NOW()
                """,
                key,
                json.dumps(payload, ensure_ascii=False),
            )