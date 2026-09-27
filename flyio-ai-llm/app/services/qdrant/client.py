"""Qdrant client singleton and connection manager."""

from typing import Optional
from qdrant_client import AsyncQdrantClient, QdrantClient

from app.core.config import Settings, get_settings
from app.core.logging import logger


class QdrantClientManager:
    """Manages reusable Qdrant client instances."""

    _async_client: Optional[AsyncQdrantClient] = None
    _sync_client: Optional[QdrantClient] = None

    @classmethod
    def get_async_client(cls, settings: Optional[Settings] = None) -> AsyncQdrantClient:
        """Get or initialize the reusable asynchronous Qdrant client."""
        if cls._async_client is None:
            cfg = settings or get_settings()
            logger.info(
                f"Initializing AsyncQdrantClient connecting to {cfg.QDRANT_URL}",
                extra={"event": "qdrant_client_init"},
            )
            cls._async_client = AsyncQdrantClient(
                url=cfg.QDRANT_URL,
                api_key=cfg.QDRANT_API_KEY if cfg.QDRANT_API_KEY else None,
                timeout=cfg.QDRANT_TIMEOUT,
            )
        return cls._async_client

    @classmethod
    def get_sync_client(cls, settings: Optional[Settings] = None) -> QdrantClient:
        """Get or initialize the reusable synchronous Qdrant client."""
        if cls._sync_client is None:
            cfg = settings or get_settings()
            cls._sync_client = QdrantClient(
                url=cfg.QDRANT_URL,
                api_key=cfg.QDRANT_API_KEY if cfg.QDRANT_API_KEY else None,
                timeout=cfg.QDRANT_TIMEOUT,
            )
        return cls._sync_client

    @classmethod
    async def close(cls) -> None:
        """Gracefully close clients on shutdown."""
        if cls._async_client is not None:
            try:
                await cls._async_client.close()
            except Exception as e:
                logger.warning(f"Error closing AsyncQdrantClient: {e}", extra={"event": "qdrant_client_close_error"})
            finally:
                cls._async_client = None
        if cls._sync_client is not None:
            try:
                cls._sync_client.close()
            except Exception:
                pass
            finally:
                cls._sync_client = None
