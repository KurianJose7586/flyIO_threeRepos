"""Qdrant service operations: connection, collection initialization, health, and vector search."""

from typing import Any, Dict, List, Optional
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import Settings, get_settings
from app.core.context import get_request_id
from app.core.errors import AppException, InvalidRequestError, QdrantUnavailableError
from app.core.logging import logger
from app.schemas.health import QdrantHealthResponse
from app.schemas.search import SearchResult, SearchResultItem
from app.services.qdrant.client import QdrantClientManager


class QdrantService:
    """Service layer managing Qdrant vector database interactions."""

    def __init__(
        self,
        client: Optional[AsyncQdrantClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or QdrantClientManager.get_async_client(self.settings)

    async def check_health(self) -> QdrantHealthResponse:
        """Verify live connectivity and collection status with Qdrant."""
        req_id = get_request_id() or "none"
        collection_name = self.settings.QDRANT_COLLECTION_NAME

        try:
            # Test connectivity by listing collections
            collections_response = await self.client.get_collections()
            collection_names = [col.name for col in collections_response.collections]
            collection_exists = collection_name in collection_names

            status_text = "connected"
            details = (
                f"Connected to Qdrant. Collection '{collection_name}' exists."
                if collection_exists
                else f"Connected to Qdrant. Collection '{collection_name}' not yet created."
            )

            logger.info(
                f"Qdrant health check successful: collection_exists={collection_exists}",
                extra={"event": "qdrant_health_check_success"},
            )

            from datetime import datetime, timezone

            return QdrantHealthResponse(
                status=status_text,
                connected=True,
                qdrant_url=self.settings.QDRANT_URL,
                collection_name=collection_name,
                collection_exists=collection_exists,
                vector_size=self.settings.EMBEDDING_DIMENSION,
                request_id=req_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                details=details,
            )
        except Exception as exc:
            logger.error(
                f"Qdrant health check failed: {str(exc)}",
                extra={"event": "qdrant_health_check_failed"},
            )
            from datetime import datetime, timezone

            return QdrantHealthResponse(
                status="unavailable",
                connected=False,
                qdrant_url=self.settings.QDRANT_URL,
                collection_name=collection_name,
                collection_exists=False,
                vector_size=self.settings.EMBEDDING_DIMENSION,
                request_id=req_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                details=f"Failed to connect to Qdrant: {str(exc)}",
            )

    async def ensure_collection(
        self,
        collection_name: Optional[str] = None,
        vector_size: Optional[int] = None,
    ) -> bool:
        """Safely ensure the configured collection exists without destroying existing data.

        Returns True if collection exists or was created, False if creation failed.
        """
        col_name = collection_name or self.settings.QDRANT_COLLECTION_NAME
        dim = vector_size or self.settings.EMBEDDING_DIMENSION

        try:
            exists = await self.client.collection_exists(collection_name=col_name)
            if exists:
                logger.info(
                    f"Qdrant collection '{col_name}' already exists. Preserving existing data.",
                    extra={"event": "qdrant_collection_exists"},
                )
                return True

            logger.info(
                f"Collection '{col_name}' does not exist. Creating with dimension {dim} (Cosine)...",
                extra={"event": "qdrant_collection_create"},
            )
            await self.client.create_collection(
                collection_name=col_name,
                vectors_config=models.VectorParams(
                    size=dim,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(
                f"Qdrant collection '{col_name}' created successfully.",
                extra={"event": "qdrant_collection_created"},
            )
            return True
        except Exception as exc:
            logger.error(
                f"Failed to ensure Qdrant collection '{col_name}': {str(exc)}",
                extra={"event": "qdrant_collection_ensure_error"},
            )
            return False

    async def search(
        self,
        query_vector: List[float],
        collection_name: Optional[str] = None,
        limit: Optional[int] = None,
        score_threshold: Optional[float] = None,
    ) -> SearchResult:
        """Execute vector search in Qdrant and return structured result.

        Distinguishes:
        - Data Found: Matching vectors found above score threshold
        - Data Not Found: Search completed but no vector matched above threshold or collection is empty
        - Search Failed: Qdrant unreachable or execution error (raises QdrantUnavailableError)
        """
        req_id = get_request_id() or "none"
        col_name = collection_name or self.settings.QDRANT_COLLECTION_NAME
        search_limit = limit or self.settings.QDRANT_SEARCH_LIMIT
        threshold = score_threshold if score_threshold is not None else self.settings.QDRANT_SEARCH_SCORE_THRESHOLD

        logger.info(
            f"Executing Qdrant vector search in '{col_name}' (limit={search_limit}, threshold={threshold})",
            extra={"event": "qdrant_search_started"},
        )

        try:
            # Check if collection exists first; if not, ensure it or return empty
            exists = await self.client.collection_exists(collection_name=col_name)
            if not exists:
                logger.info(
                    f"Collection '{col_name}' does not exist yet. Ensuring collection creation...",
                    extra={"event": "qdrant_search_collection_missing"},
                )
                created = await self.ensure_collection(col_name)
                if not created:
                    return SearchResult(
                        found=False,
                        data_required=True,
                        total_results=0,
                        results=[],
                        request_id=req_id,
                        message="Vector collection does not exist yet. Source data scraping required.",
                    )

            # Execute vector search
            if hasattr(self.client, "query_points"):
                response = await self.client.query_points(
                    collection_name=col_name,
                    query=query_vector,
                    limit=search_limit,
                    score_threshold=threshold,
                    with_payload=True,
                )
                points = response.points
            else:
                points = await self.client.search(
                    collection_name=col_name,
                    query_vector=query_vector,
                    limit=search_limit,
                    score_threshold=threshold,
                    with_payload=True,
                )

            items: List[SearchResultItem] = []
            for pt in points:
                payload = pt.payload or {}
                text_content = payload.get("text") or payload.get("content") or payload.get("body")
                items.append(
                    SearchResultItem(
                        id=pt.id,
                        score=float(pt.score),
                        payload=payload,
                        text=str(text_content) if text_content else None,
                    )
                )

            if items:
                logger.info(
                    f"Qdrant search succeeded: found {len(items)} matching items",
                    extra={"event": "qdrant_search_data_found"},
                )
                return SearchResult(
                    found=True,
                    data_required=False,
                    total_results=len(items),
                    results=items,
                    request_id=req_id,
                    message=f"Found {len(items)} relevant document(s) in vector knowledge base",
                )
            else:
                logger.info(
                    "Qdrant search completed: no items matched above threshold",
                    extra={"event": "qdrant_search_data_missing"},
                )
                return SearchResult(
                    found=False,
                    data_required=True,
                    total_results=0,
                    results=[],
                    request_id=req_id,
                    message="No relevant data found in vector knowledge base. Source data scraping required.",
                )

        except UnexpectedResponse as err:
            logger.error(
                f"Qdrant returned unexpected response: status={err.status_code} reason={err.reason_phrase}",
                extra={"event": "qdrant_search_failed"},
            )
            raise QdrantUnavailableError(
                message=f"Qdrant query failed: {err.reason_phrase}",
                details={"status_code": err.status_code},
            )
        except AppException:
            raise
        except Exception as exc:
            logger.error(
                f"Qdrant vector search failed: {str(exc)}",
                extra={"event": "qdrant_search_error"},
            )
            raise QdrantUnavailableError(
                message="Vector database is currently unavailable or search query failed",
                details={"error": str(exc)},
            )

    async def validate_collection(
        self,
        collection_name: str,
        expected_size: Optional[int] = None,
    ) -> bool:
        """Validate that requested collection exists and vector configuration matches requirements.

        Raises InvalidRequestError (HTTP 400) if collection is missing or has mismatched vector dimension.
        """
        target_size = expected_size or self.settings.EMBEDDING_DIMENSION

        try:
            exists = await self.client.collection_exists(collection_name=collection_name)
            if not exists:
                logger.warning(
                    f"Collection validation failed: '{collection_name}' does not exist",
                    extra={"event": "qdrant_collection_validation_missing"},
                )
                raise InvalidRequestError(
                    message=f"Collection '{collection_name}' does not exist in vector database.",
                    details={"collection_name": collection_name},
                )

            # Inspect collection configuration to verify vector layout and dimension.
            #
            # params.vectors is either:
            #   - VectorParams            -> a single unnamed/default vector (what this
            #                                client writes and queries), has .size
            #   - dict[str, VectorParams] -> NAMED vectors, keyed by vector name
            #
            # The named case matters: this service upserts with a bare
            # `vector=[...]` and queries without `using=`, which a named-vector
            # collection rejects outright ("Not existing vector name error").
            # An earlier version of this check looked for `params.vectors["size"]`
            # on the dict, which is never a real key (the keys are vector *names*),
            # so col_vector_size stayed None, the mismatch branch was skipped, and
            # validation silently PASSED against a collection this service cannot
            # actually write to — the exact failure this check exists to prevent.
            info = await self.client.get_collection(collection_name=collection_name)
            col_vector_size = None
            if hasattr(info, "config") and info.config:
                params = info.config.params
                vectors = getattr(params, "vectors", None)
                if vectors:
                    if hasattr(vectors, "size"):
                        col_vector_size = vectors.size
                    elif isinstance(vectors, dict):
                        named = {name: getattr(cfg, "size", None) for name, cfg in vectors.items()}
                        logger.warning(
                            f"Collection '{collection_name}' uses named vectors {named}; "
                            "this service reads/writes unnamed (default) vectors.",
                            extra={"event": "qdrant_collection_named_vectors_unsupported"},
                        )
                        raise InvalidRequestError(
                            message=(
                                f"Collection '{collection_name}' is configured with named vectors "
                                f"({', '.join(named)}), but this service reads and writes unnamed "
                                "(default) vectors. Recreate the collection with a single unnamed "
                                "vector, or point QDRANT_COLLECTION_NAME at one that has it."
                            ),
                            details={"named_vectors": named, "expected_size": target_size},
                        )

            if col_vector_size is not None and col_vector_size != target_size:
                logger.warning(
                    f"Collection '{collection_name}' vector dimension mismatch: found={col_vector_size}, expected={target_size}",
                    extra={"event": "qdrant_collection_validation_mismatch"},
                )
                raise InvalidRequestError(
                    message=f"Collection '{collection_name}' vector size mismatch (found {col_vector_size}, expected {target_size}).",
                    details={"collection_size": col_vector_size, "expected_size": target_size},
                )

            return True
        except AppException:
            raise
        except Exception as exc:
            logger.error(
                f"Failed collection validation for '{collection_name}': {str(exc)}",
                extra={"event": "qdrant_collection_validation_error"},
            )
            raise QdrantUnavailableError(
                message="Vector database is currently unavailable or collection validation failed",
                details={"error": str(exc)},
            )

    async def upsert_points(
        self,
        points: List[Dict[str, Any]],
        collection_name: Optional[str] = None,
    ) -> bool:
        """Upsert vector points into Qdrant in a single atomic batch operation (all-or-nothing atomicity).

        Ensures default collection creation or validates custom collection presence first.
        """
        col_name = collection_name or self.settings.QDRANT_COLLECTION_NAME

        # If using default collection, ensure creation first
        if col_name == self.settings.QDRANT_COLLECTION_NAME:
            await self.ensure_collection(col_name)

        # Validate collection existence and vector dimension size before writing
        await self.validate_collection(col_name)

        qdrant_points = [
            models.PointStruct(
                id=pt["id"],
                vector=pt["vector"],
                payload=pt.get("payload", {}),
            )
            for pt in points
        ]

        try:
            logger.info(
                f"Executing atomic Qdrant upsert: {len(qdrant_points)} vector point(s) into collection '{col_name}'",
                extra={"event": "qdrant_insert_started"},
            )
            # Atomic single call batch upsert
            await self.client.upsert(
                collection_name=col_name,
                points=qdrant_points,
            )
            logger.info(
                f"Successfully completed Qdrant upsert: {len(qdrant_points)} point(s) inserted/updated",
                extra={"event": "qdrant_insert_completed"},
            )
            return True
        except UnexpectedResponse as err:
            logger.error(
                f"Qdrant returned unexpected response on upsert: status={err.status_code} reason={err.reason_phrase}",
                extra={"event": "qdrant_insert_failed"},
            )
            raise QdrantUnavailableError(
                message=f"Qdrant vector storage failed: {err.reason_phrase}",
                details={"status_code": err.status_code},
            )
        except AppException:
            raise
        except Exception as exc:
            logger.error(
                f"Failed to upsert points into Qdrant collection '{col_name}': {str(exc)}",
                extra={"event": "qdrant_insert_error"},
            )
            raise QdrantUnavailableError(
                message="Vector database is currently unavailable or storage write failed",
                details={"error": str(exc)},
            )

