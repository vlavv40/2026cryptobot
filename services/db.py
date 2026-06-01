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
            ADD COLUMN IF NOT EXISTS active_stop_loss DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS signal_type TEXT NOT NULL DEFAULT 'UNKNOWN',
            ADD COLUMN IF NOT EXISTS protection_stage TEXT NOT NULL DEFAULT 'INITIAL',
            ADD COLUMN IF NOT EXISTS tp1_hit_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS tp2_hit_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS protection_updated_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS entry_price DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS initial_position_qty DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS tp1_qty DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS tp2_qty DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS tp3_qty DOUBLE PRECISION;
            """)

            await conn.execute("""
            UPDATE tracked_signals
            SET active_stop_loss = stop_loss
            WHERE active_stop_loss IS NULL;
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

            await conn.execute("""
            ALTER TABLE paper_trades
            ADD COLUMN IF NOT EXISTS active_stop_loss DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS protection_stage TEXT NOT NULL DEFAULT 'INITIAL',
            ADD COLUMN IF NOT EXISTS tp1_hit_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS tp2_hit_at TIMESTAMP,
            ADD COLUMN IF NOT EXISTS protection_updated_at TIMESTAMP;
            """)

            await conn.execute("""
            UPDATE paper_trades
            SET active_stop_loss = stop_loss
            WHERE active_stop_loss IS NULL;
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS strategy_parameters (
                key TEXT PRIMARY KEY,
                value JSONB NOT NULL,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS symbol_whitelist (
                symbol TEXT PRIMARY KEY,
                expectancy DOUBLE PRECISION NOT NULL DEFAULT 0,
                winrate DOUBLE PRECISION NOT NULL DEFAULT 0,
                total_r DOUBLE PRECISION NOT NULL DEFAULT 0,
                closed_count INTEGER NOT NULL DEFAULT 0,
                refreshed_at TIMESTAMP NOT NULL DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS equity_history (
                id BIGSERIAL PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'signals',
                equity_r DOUBLE PRECISION NOT NULL DEFAULT 0,
                balance DOUBLE PRECISION,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                snapshot_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS symbol_stats_snapshots (
                id BIGSERIAL PRIMARY KEY,
                symbol TEXT NOT NULL,
                payload JSONB NOT NULL,
                snapshot_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS symbol_stats (
                symbol TEXT PRIMARY KEY,
                signals_count INTEGER NOT NULL DEFAULT 0,
                closed_count INTEGER NOT NULL DEFAULT 0,
                open_count INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                winrate DOUBLE PRECISION NOT NULL DEFAULT 0,
                expectancy DOUBLE PRECISION NOT NULL DEFAULT 0,
                total_r DOUBLE PRECISION NOT NULL DEFAULT 0,
                avg_hold_minutes DOUBLE PRECISION NOT NULL DEFAULT 0,
                max_drawdown DOUBLE PRECISION NOT NULL DEFAULT 0,
                profit_factor TEXT NOT NULL DEFAULT '0',
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS app_users (
                id BIGSERIAL PRIMARY KEY,
                telegram_id TEXT UNIQUE,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_api_keys (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES app_users(id) ON DELETE CASCADE,
                exchange TEXT NOT NULL DEFAULT 'BINANCE_FUTURES',
                api_key TEXT,
                api_secret TEXT,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_risk_settings (
                user_id BIGINT PRIMARY KEY REFERENCES app_users(id) ON DELETE CASCADE,
                risk_per_trade DOUBLE PRECISION NOT NULL DEFAULT 0.01,
                max_open_trades INTEGER NOT NULL DEFAULT 5,
                max_total_risk DOUBLE PRECISION NOT NULL DEFAULT 0.05,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """)

            await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_subscriptions (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES app_users(id) ON DELETE CASCADE,
                plan TEXT NOT NULL DEFAULT 'DEFAULT',
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                valid_until TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW()
            );
            """)

    async def get_strategy_parameter(self, key: str):
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT value FROM strategy_parameters WHERE key=$1",
                key,
            )

    async def set_strategy_parameter(self, key: str, value: str):
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO strategy_parameters (key, value, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (key)
                DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()
                """,
                key,
                value,
            )

    async def reset_stats(self):
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO strategy_parameters (key, value, updated_at)
                    VALUES ('statistics_reset_at', to_jsonb(NOW()), NOW())
                    ON CONFLICT (key)
                    DO UPDATE SET value=to_jsonb(NOW()), updated_at=NOW()
                    """
                )
                await conn.execute("TRUNCATE paper_trades RESTART IDENTITY;")
                await conn.execute("TRUNCATE equity_history RESTART IDENTITY;")
                await conn.execute("TRUNCATE symbol_stats_snapshots RESTART IDENTITY;")
                await conn.execute("TRUNCATE symbol_whitelist;")
                await conn.execute("TRUNCATE symbol_stats;")
                await conn.execute(
                    """
                    UPDATE paper_state
                    SET start_balance=10000,
                        balance=10000,
                        risk_per_trade=0.01
                    WHERE id=1
                    """
                )

    async def reset_db(self):
        assert self.pool is not None
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("TRUNCATE bot_state_cooldowns;")
                await conn.execute("TRUNCATE bot_state_last_signals;")
                await conn.execute("TRUNCATE signal_logs RESTART IDENTITY;")
                await conn.execute("TRUNCATE tracked_signals;")
                await conn.execute("TRUNCATE paper_trades RESTART IDENTITY;")
                await conn.execute("TRUNCATE equity_history RESTART IDENTITY;")
                await conn.execute("TRUNCATE symbol_stats_snapshots RESTART IDENTITY;")
                await conn.execute("TRUNCATE symbol_whitelist;")
                await conn.execute("TRUNCATE symbol_stats;")
                await conn.execute("TRUNCATE strategy_parameters;")
                await conn.execute("""
                TRUNCATE user_subscriptions, user_risk_settings, user_api_keys, app_users
                RESTART IDENTITY;
                """)
                await conn.execute("""
                INSERT INTO paper_state (id, start_balance, balance, risk_per_trade)
                VALUES (1, 10000, 10000, 0.01)
                ON CONFLICT (id)
                DO UPDATE SET start_balance=10000, balance=10000, risk_per_trade=0.01;
                """)


db = Database()
