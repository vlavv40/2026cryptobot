import asyncpg

from config import Config


class Database:
    def __init__(self):
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        if self.pool is not None:
            return

        if not Config.POSTGRES_URI:
            raise ValueError("POSTGRES_URI не найден. Добавь его в Railway Variables")

        self.pool = await asyncpg.create_pool(Config.POSTGRES_URI, min_size=1, max_size=5)
        await self.init_schema()

    async def init_schema(self):
        assert self.pool is not None

        async with self.pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_state_cooldowns (
                key TEXT PRIMARY KEY,
                expires_at TIMESTAMP NOT NULL
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_state_last_signals (
                key TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                saved_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS signal_logs (
                id BIGSERIAL PRIMARY KEY,
                payload JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_logs (
                id BIGSERIAL PRIMARY KEY,
                level TEXT DEFAULT 'INFO',
                symbol TEXT,
                action TEXT NOT NULL,
                message TEXT NOT NULL,
                reason TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS bot_logs_id_seq;
            """)

            await conn.execute("""
            SELECT setval(
                'bot_logs_id_seq',
                GREATEST(COALESCE((SELECT MAX(id) FROM bot_logs), 0) + 1, 1),
                false
            );
            """)

            await conn.execute("""
            ALTER TABLE bot_logs
            ALTER COLUMN id SET DEFAULT nextval('bot_logs_id_seq');
            """)

            await conn.execute("""
            ALTER SEQUENCE bot_logs_id_seq OWNED BY bot_logs.id;
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS tracked_signals (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_min DOUBLE PRECISION NOT NULL,
                entry_max DOUBLE PRECISION NOT NULL,
                stop_loss DOUBLE PRECISION NOT NULL,
                tp1 DOUBLE PRECISION NOT NULL,
                tp2 DOUBLE PRECISION NOT NULL,
                tp3 DOUBLE PRECISION NOT NULL,
                score DOUBLE PRECISION NOT NULL,
                status TEXT NOT NULL,
                realized_r DOUBLE PRECISION,
                created_at TIMESTAMP NOT NULL,
                closed_at TIMESTAMP,
                notified BOOLEAN NOT NULL DEFAULT FALSE
            );
            """)

            await conn.execute("""
            ALTER TABLE tracked_signals
            ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'bot',
            ADD COLUMN IF NOT EXISTS strategy TEXT,
            ADD COLUMN IF NOT EXISTS current_price DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS exit_price DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS reason TEXT,
            ADD COLUMN IF NOT EXISTS indicators_json JSONB,
            ADD COLUMN IF NOT EXISTS status_log_json JSONB DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS hidden BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS invalid_reason TEXT;
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_state (
                id INTEGER PRIMARY KEY,
                start_balance DOUBLE PRECISION NOT NULL,
                balance DOUBLE PRECISION NOT NULL,
                risk_per_trade DOUBLE PRECISION NOT NULL
            );
            """)

            await conn.execute("""
            INSERT INTO paper_state (id, start_balance, balance, risk_per_trade)
            VALUES (1, 10000, 10000, 0.01)
            ON CONFLICT (id) DO NOTHING;
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id BIGSERIAL PRIMARY KEY,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                entry_min DOUBLE PRECISION NOT NULL,
                entry_max DOUBLE PRECISION NOT NULL,
                entry_price DOUBLE PRECISION NOT NULL,
                stop_loss DOUBLE PRECISION NOT NULL,
                tp1 DOUBLE PRECISION NOT NULL,
                tp2 DOUBLE PRECISION NOT NULL,
                tp3 DOUBLE PRECISION NOT NULL,
                size DOUBLE PRECISION NOT NULL,
                risk_amount DOUBLE PRECISION NOT NULL,
                status TEXT NOT NULL,
                result_usdt DOUBLE PRECISION NOT NULL DEFAULT 0,
                result_r DOUBLE PRECISION NOT NULL DEFAULT 0,
                close_reason TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                closed_at TIMESTAMP
            );
            """)


db = Database()
