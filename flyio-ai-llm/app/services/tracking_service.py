"""Event tracking service for durable PostgreSQL persistence."""

import asyncio
import json
from typing import Any, Dict, Optional

from app.core.config import Settings, get_settings
from app.core.context import get_request_id
from app.core.logging import logger
from app.db.session import DatabaseManager


_background_tasks: set[asyncio.Task] = set()


class TrackingService:
    """Service managing durable event persistence in PostgreSQL.

    Guarantees non-blocking fire-and-forget execution with fail-safe isolation.
    Database outages never impact API availability or response latency.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    @classmethod
    async def drain_tasks(cls, timeout: float = 3.0) -> None:
        """Await all in-flight tracking tasks before application shutdown to prevent event loss."""
        if not _background_tasks:
            return
        logger.info(f"Draining {len(_background_tasks)} in-flight tracking task(s)...", extra={"event": "db_drain_tasks"})
        try:
            await asyncio.wait_for(
                asyncio.gather(*list(_background_tasks), return_exceptions=True),
                timeout=timeout,
            )
        except Exception as exc:
            logger.warning(f"Timeout/error draining tracking tasks: {exc}", extra={"event": "db_drain_tasks_warning"})

    def log_event(
        self,
        event_type: str,
        status: str = "info",
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Schedule non-blocking event persistence in PostgreSQL via background task."""
        eff_request_id = request_id or get_request_id() or "none"
        eff_metadata = metadata or {}

        # Log via application logger first
        logger.info(
            f"Event: {event_type} status={status} msg='{message or ''}'",
            extra={"event": event_type, "request_id": eff_request_id},
        )

        if not self.settings.DATABASE_ENABLED or not self.settings.DATABASE_URL:
            return

        # Fire-and-forget background task retained in strong set to prevent GC mid-write
        task = asyncio.create_task(
            self._persist_event(
                request_id=eff_request_id,
                service=self.settings.PROJECT_NAME,
                event_type=event_type,
                status=status,
                message=message,
                metadata=eff_metadata,
            )
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


    async def _persist_event(
        self,
        request_id: str,
        event_type: str,
        status: str,
        message: Optional[str],
        metadata: Dict[str, Any],
        service: Optional[str] = None,
    ) -> bool:
        """Internal helper to write event row to PostgreSQL. Suppresses all database exceptions."""
        try:
            pool = await DatabaseManager.get_pool(settings=self.settings)
            if pool is None:
                return False

            meta_json = json.dumps(metadata)
            eff_service = service or self.settings.PROJECT_NAME

            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO request_events (request_id, service, event_type, status, message, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb);
                    """,
                    request_id,
                    eff_service,
                    event_type,
                    status,
                    message,
                    meta_json,
                )
            return True
        except Exception as exc:
            logger.warning(
                f"Failed to persist event '{event_type}' to PostgreSQL: {exc}. Suppressing exception.",
                extra={"event": "event_tracking_db_warning", "request_id": request_id},
            )
            return False
