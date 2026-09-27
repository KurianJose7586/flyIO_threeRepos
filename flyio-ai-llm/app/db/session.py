"""Database session manager for asyncpg connection pool."""

import asyncpg
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.context import get_request_id
from app.core.logging import logger
from app.schemas.health import PostgresHealthResponse

_db_pool: Optional[asyncpg.Pool] = None


class DatabaseManager:
    """Manages asyncpg connection pool lifespan and DDL initialization."""

    @classmethod
    async def get_pool(cls, settings: Optional[Settings] = None) -> Optional[asyncpg.Pool]:
        """Return the active connection pool instance."""
        global _db_pool
        if _db_pool is None:
            await cls.init_db(settings=settings)
        return _db_pool

    @classmethod
    async def init_db(cls, settings: Optional[Settings] = None) -> Optional[asyncpg.Pool]:
        """Initialize connection pool and execute DDL table creation safely."""
        global _db_pool
        cfg = settings or get_settings()

        if not cfg.DATABASE_ENABLED or not cfg.DATABASE_URL:
            logger.info(
                "PostgreSQL database tracking is disabled or DATABASE_URL is empty.",
                extra={"event": "db_init_disabled"},
            )
            return None

        if _db_pool is not None:
            return _db_pool

        try:
            # Convert connection scheme if needed for asyncpg (e.g., postgresql://)
            dsn = cfg.DATABASE_URL
            if dsn.startswith("postgresql+asyncpg://"):
                dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

            logger.info("Initializing PostgreSQL asyncpg connection pool...", extra={"event": "db_init_started"})
            _db_pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=1,
                max_size=10,
                command_timeout=5.0,
                timeout=5.0,
            )

            # Run DDL table initialization
            sql_file = Path(__file__).parent / "init.sql"
            if sql_file.exists():
                ddl_sql = sql_file.read_text(encoding="utf-8")
            else:
                # Kept in sync with app/db/init.sql — this only runs if that file is
                # missing from the deployed image.
                ddl_sql = """
                CREATE TABLE IF NOT EXISTS request_events (
                    id BIGSERIAL PRIMARY KEY,
                    request_id VARCHAR(64) NOT NULL,
                    service VARCHAR(32) NOT NULL DEFAULT 'flyio-ai-llm',
                    event_type VARCHAR(64) NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'info',
                    message TEXT,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                ALTER TABLE request_events ADD COLUMN IF NOT EXISTS service VARCHAR(32) NOT NULL DEFAULT 'flyio-ai-llm';
                CREATE INDEX IF NOT EXISTS idx_request_events_request_id ON request_events(request_id);
                CREATE INDEX IF NOT EXISTS idx_request_events_event_type ON request_events(event_type);
                CREATE INDEX IF NOT EXISTS idx_request_events_request_id_service ON request_events(request_id, service);
                """

            async with _db_pool.acquire() as conn:
                await conn.execute(ddl_sql)

            logger.info("PostgreSQL request_events table initialized successfully.", extra={"event": "db_init_success"})
            return _db_pool
        except Exception as exc:
            logger.warning(
                f"Could not connect to PostgreSQL or initialize schema: {exc}. Service will run in fail-safe mode.",
                extra={"event": "db_init_warning"},
            )
            _db_pool = None
            return None

    @classmethod
    async def check_health(cls, settings: Optional[Settings] = None) -> PostgresHealthResponse:
        """Actively verify PostgreSQL connectivity for the /health/postgres endpoint.

        Event tracking failures are deliberately suppressed everywhere else in this
        service (see TrackingService) so a database outage never breaks the API. That
        means an outage is otherwise silent — this is the one place it's surfaced.
        """
        cfg = settings or get_settings()
        req_id = get_request_id() or "none"
        timestamp = datetime.now(timezone.utc).isoformat()

        if not cfg.DATABASE_ENABLED or not cfg.DATABASE_URL:
            return PostgresHealthResponse(
                status="disabled",
                connected=False,
                database_enabled=cfg.DATABASE_ENABLED,
                request_id=req_id,
                timestamp=timestamp,
                details="PostgreSQL event tracking is disabled or DATABASE_URL is not configured.",
            )

        try:
            pool = await cls.get_pool(settings=cfg)
            if pool is None:
                raise RuntimeError("Connection pool could not be established.")

            # Confirm the connection is actually live, not just that a pool object
            # exists — a pool created successfully at startup can go stale later.
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1;")

            logger.info("PostgreSQL health check successful.", extra={"event": "db_health_check_success"})
            return PostgresHealthResponse(
                status="connected",
                connected=True,
                database_enabled=True,
                request_id=req_id,
                timestamp=timestamp,
                details="Connected. Event tracking is active.",
            )
        except Exception as exc:
            logger.error(
                f"PostgreSQL health check failed: {exc}",
                extra={"event": "db_health_check_failed"},
            )
            return PostgresHealthResponse(
                status="unavailable",
                connected=False,
                database_enabled=True,
                request_id=req_id,
                timestamp=timestamp,
                details=f"PostgreSQL is unreachable: {exc}",
            )

    @classmethod
    async def close(cls) -> None:
        """Drain in-flight background tracking tasks and close connection pool gracefully during shutdown."""
        global _db_pool
        from app.services.tracking_service import TrackingService

        try:
            await TrackingService.drain_tasks()
        except Exception as drain_exc:
            logger.warning(f"Error draining tracking tasks during shutdown: {drain_exc}")

        if _db_pool is not None:
            logger.info("Closing PostgreSQL asyncpg connection pool...", extra={"event": "db_shutdown"})
            try:
                await _db_pool.close()
            except Exception as exc:
                logger.warning(f"Error closing DB pool: {exc}", extra={"event": "db_shutdown_error"})
            _db_pool = None

