"""Unit tests for TrackingService and DatabaseManager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.config import Settings
from app.db.session import DatabaseManager
from app.services.tracking_service import TrackingService


@pytest.mark.asyncio
async def test_tracking_service_log_event_dispatches_task(test_settings: Settings):
    """Test log_event schedules _persist_event without blocking caller."""
    tracking_svc = TrackingService(settings=test_settings)

    with patch.object(tracking_svc, "_persist_event", new_callable=AsyncMock) as mock_persist:
        mock_persist.return_value = True

        tracking_svc.log_event(
            event_type="test_event",
            status="started",
            message="Unit test event log",
            metadata={"key": "val"},
            request_id="req_track_001",
        )

        # Allow asyncio event loop to execute task
        await asyncio.sleep(0.05)
        mock_persist.assert_called_once_with(
            request_id="req_track_001",
            service=test_settings.PROJECT_NAME,
            event_type="test_event",
            status="started",
            message="Unit test event log",
            metadata={"key": "val"},
        )


@pytest.mark.asyncio
async def test_tracking_service_persist_event_success(test_settings: Settings):
    """Test _persist_event executes PostgreSQL insert query via connection pool."""
    tracking_svc = TrackingService(settings=test_settings)

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=None)

    mock_acq = MagicMock()
    mock_acq.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acq.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acq

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock) as mock_get_pool:
        mock_get_pool.return_value = mock_pool


        result = await tracking_svc._persist_event(
            request_id="req_track_002",
            event_type="qdrant_search_started",
            status="started",
            message="Executing search",
            metadata={"threshold": 0.7},
        )

        assert result is True
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        query = call_args[0]
        assert "INSERT INTO request_events" in query
        assert "service" in query
        # service was not passed explicitly, so _persist_event must fall back to
        # settings.PROJECT_NAME rather than silently omitting/blanking the column.
        assert call_args[2] == test_settings.PROJECT_NAME


@pytest.mark.asyncio
async def test_tracking_service_persist_event_uses_explicit_service_when_given(test_settings: Settings):
    """Test _persist_event stores the explicit `service` argument (as log_event
    passes it) rather than always defaulting to settings.PROJECT_NAME."""
    tracking_svc = TrackingService(settings=test_settings)

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=None)

    mock_acq = MagicMock()
    mock_acq.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acq.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = mock_acq

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock) as mock_get_pool:
        mock_get_pool.return_value = mock_pool

        await tracking_svc._persist_event(
            request_id="req_track_003",
            service="flyio-scraper-service",
            event_type="url_scraped",
            status="completed",
            message="Scraped 1 URL",
            metadata={},
        )

        call_args = mock_conn.execute.call_args[0]
        assert call_args[2] == "flyio-scraper-service"


@pytest.mark.asyncio
async def test_tracking_service_fail_safe_isolation_on_db_exception(test_settings: Settings):
    """Test _persist_event suppresses database exceptions and returns False without throwing."""
    tracking_svc = TrackingService(settings=test_settings)

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock) as mock_get_pool:
        mock_get_pool.side_effect = Exception("PostgreSQL connection refused")

        result = await tracking_svc._persist_event(
            request_id="req_fail_safe_01",
            event_type="store_started",
            status="started",
            message="Testing fail safe error handling",
            metadata={},
        )

        assert result is False



@pytest.mark.asyncio
async def test_tracking_service_database_disabled_noop():
    """Test DATABASE_ENABLED=False makes TrackingService a clean no-op."""
    disabled_settings = Settings(DATABASE_ENABLED=False)
    svc = TrackingService(settings=disabled_settings)

    with patch.object(svc, "_persist_event", new_callable=AsyncMock) as mock_persist:
        svc.log_event("test_event", request_id="req_disabled_1")
        await asyncio.sleep(0.02)
        mock_persist.assert_not_called()


@pytest.mark.asyncio
async def test_tracking_service_task_retained_and_drained(test_settings: Settings):
    """Test background tasks are retained in strong set and drained gracefully."""
    svc = TrackingService(settings=test_settings)

    with patch.object(svc, "_persist_event", new_callable=AsyncMock) as mock_persist:
        async def dummy_persist(*args, **kwargs):
            await asyncio.sleep(0.01)
            return True

        mock_persist.side_effect = dummy_persist

        svc.log_event("long_running_event", request_id="req_drain_1")
        await TrackingService.drain_tasks(timeout=1.0)
        mock_persist.assert_called_once()




def test_init_sql_idempotent_schema():
    """Test init.sql uses CREATE TABLE IF NOT EXISTS and CREATE INDEX IF NOT EXISTS."""
    from pathlib import Path
    sql_file = Path(__file__).parent.parent / "app" / "db" / "init.sql"
    assert sql_file.exists()
    content = sql_file.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS request_events" in content
    assert "CREATE INDEX IF NOT EXISTS idx_request_events_request_id" in content
    assert "CREATE INDEX IF NOT EXISTS idx_request_events_event_type" in content


def test_init_sql_has_service_column_for_cross_service_tracking():
    """The `service` column identifies which of the three FlyIO microservices wrote
    a row, which is required since all three write to one shared database
    (see FlyIO_Project_Context.md section 4). Both the CREATE TABLE definition and
    a standalone ADD COLUMN IF NOT EXISTS must be present so the column also lands
    on a `request_events` table created by an older version of this script, or by
    another service, before this column existed.
    """
    from pathlib import Path
    sql_file = Path(__file__).parent.parent / "app" / "db" / "init.sql"
    content = sql_file.read_text(encoding="utf-8")
    assert "service VARCHAR(32) NOT NULL DEFAULT 'flyio-ai-llm'" in content
    assert "ALTER TABLE request_events ADD COLUMN IF NOT EXISTS service" in content
    assert "idx_request_events_request_id_service" in content


def test_session_fallback_ddl_matches_init_sql_schema():
    """app/db/session.py carries an inline fallback DDL string for the (unlikely)
    case init.sql is missing from the deployed image. It must not drift from the
    real init.sql schema — in particular it must also define the `service` column.
    """
    import inspect
    from app.db import session as session_module

    source = inspect.getsource(session_module)
    assert "service VARCHAR(32) NOT NULL DEFAULT 'flyio-ai-llm'" in source
    assert "ADD COLUMN IF NOT EXISTS service" in source

