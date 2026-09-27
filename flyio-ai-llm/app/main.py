"""Main FastAPI application entry point for flyio-ai-llm service."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.api import api_router
from app.core.config import get_settings
from app.core.context import get_request_id
from app.core.errors import AppException
from app.core.logging import logger, setup_logging
from app.middlewares.request_id import RequestIdMiddleware
from app.middlewares.service_auth import ServiceAuthMiddleware
from app.schemas.error import ErrorDetail, ErrorResponse
from app.services.qdrant.client import QdrantClientManager
from app.services.qdrant.service import QdrantService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and graceful shutdown."""
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)

    logger.info(
        f"Starting {settings.PROJECT_NAME} v{settings.VERSION} [{settings.ENVIRONMENT}]",
        extra={"event": "service_startup"},
    )

    # Initialize PostgreSQL connection pool safely if DB is enabled
    try:
        from app.db.session import DatabaseManager
        await DatabaseManager.init_db(settings=settings)
    except Exception as e:
        logger.warning(
            f"Could not initialize PostgreSQL connection pool on startup: {e}. Service will run in fail-safe mode.",
            extra={"event": "db_startup_warning"},
        )

    # Initialize Qdrant collection safely if Qdrant is reachable
    try:
        qdrant_svc = QdrantService(settings=settings)
        await qdrant_svc.ensure_collection()
    except Exception as e:
        logger.warning(
            f"Could not initialize Qdrant collection on startup: {e}. Will retry on request.",
            extra={"event": "qdrant_startup_warning"},
        )

    yield

    logger.info(f"Shutting down {settings.PROJECT_NAME}...", extra={"event": "service_shutdown"})
    await QdrantClientManager.close()
    try:
        from app.db.session import DatabaseManager
        await DatabaseManager.close()
    except Exception as e:
        logger.warning(f"Error during DB pool shutdown: {e}")



def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title="FlyIO AI/LLM Service",
        description="LLM plan generation, Qdrant store workflow, and event tracking for the FlyIO Travel Planner",
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Service-to-service auth (guards /v1/*, see app/middlewares/service_auth.py).
    # Added between CORS and RequestId in this call sequence so, at runtime
    # (Starlette executes last-added-first), RequestIdMiddleware still runs
    # first and sets request_id context before auth runs — so a 401 gets
    # logged/traced under the right request_id — while CORS remains closest
    # to the route handlers, unchanged from before this middleware existed.
    app.add_middleware(ServiceAuthMiddleware)

    # Correlation Request ID middleware
    app.add_middleware(RequestIdMiddleware)

    # Register Exception Handlers
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        req_id = get_request_id() or "none"
        logger.error(
            f"AppException: code={exc.code} message={exc.message}",
            extra={"event": "app_exception", "request_id": req_id},
        )
        error_resp = ErrorResponse(
            success=False,
            request_id=req_id,
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                details=exc.details,
            ),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_resp.model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        req_id = get_request_id() or "none"
        # Format field errors cleanly
        field_errors = []
        for error in exc.errors():
            loc = " -> ".join(str(item) for item in error.get("loc", []))
            msg = error.get("msg")
            field_errors.append(f"{loc}: {msg}")

        logger.warning(
            f"Request validation failed: {field_errors}",
            extra={"event": "request_validation_failed", "request_id": req_id},
        )
        error_resp = ErrorResponse(
            success=False,
            request_id=req_id,
            error=ErrorDetail(
                code="VALIDATION_ERROR",
                message="Request validation failed. Please check your payload parameters.",
                details=field_errors,
            ),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=error_resp.model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        req_id = get_request_id() or "none"
        code_map = {
            400: "INVALID_REQUEST",
            401: "UNAUTHORIZED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            500: "INTERNAL_SERVER_ERROR",
            503: "SERVICE_UNAVAILABLE",
        }
        error_code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
        error_resp = ErrorResponse(
            success=False,
            request_id=req_id,
            error=ErrorDetail(
                code=error_code,
                message=str(exc.detail),
            ),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error_resp.model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = get_request_id() or "none"
        logger.exception(
            f"Unhandled exception: {str(exc)}",
            extra={"event": "unhandled_exception", "request_id": req_id},
        )
        error_resp = ErrorResponse(
            success=False,
            request_id=req_id,
            error=ErrorDetail(
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected internal server error occurred.",
            ),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_resp.model_dump(),
        )

    # Mount versioned API routes (/v1)
    app.include_router(api_router, prefix=settings.API_V1_STR)

    # Mount root level health routes for external load balancers and orchestrators
    from app.api.v1.endpoints import health

    app.include_router(health.router)

    return app


app = create_app()
