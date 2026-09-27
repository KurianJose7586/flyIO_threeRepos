"""Structured logging configuration for flyio-ai-llm service."""

import json
import logging
import sys
from datetime import datetime, timezone

from app.core.context import get_request_id


def _common_fields(record: logging.LogRecord) -> dict:
    """Fields both formatters below share, pulled from `extra={...}` (see
    every `logger.<level>(..., extra={"event": ..., "request_id": ...})`
    call site in this codebase) with sensible fallbacks.
    """
    return {
        "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
        "level": record.levelname,
        "service": getattr(record, "service", "flyio-ai-llm"),
        "request_id": getattr(record, "request_id", None) or get_request_id() or "none",
        "event": getattr(record, "event", "general"),
        "message": record.getMessage(),
    }


class JSONFormatter(logging.Formatter):
    """One JSON object per line (JSONL) — the default (see
    Settings.LOG_FORMAT). Includes the exception traceback when present
    (record.exc_info), e.g. from logger.exception() in main.py's
    unhandled-exception handler — the plain-text formatter historically
    dropped this entirely; fixed here and below.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = _common_fields(record)
        payload["logger"] = record.name
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # default=str: defensive only — every field above is already a
        # JSON-safe primitive, but this avoids a logging call itself ever
        # crashing the process over an unexpected value type.
        return json.dumps(payload, default=str)


class StructuredFormatter(logging.Formatter):
    """Single-line key=value format for a more readable local terminal
    during development (LOG_FORMAT=text).

    Example output:
    2026-08-15T04:10:00.000Z [INFO] [flyio-ai-llm] request_id=req_12345 event=llm_request_started message="Incoming generate request"
    """

    def format(self, record: logging.LogRecord) -> str:
        f = _common_fields(record)
        line = (
            f"{f['timestamp']} [{f['level']}] [{f['service']}] "
            f"request_id={f['request_id']} event={f['event']} message={f['message']}"
        )
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> logging.Logger:
    """Configure the application's root logger.

    log_format: "json" (default, see Settings.LOG_FORMAT) or "text".
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    # Clear existing handlers to prevent duplicate output
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    formatter = JSONFormatter() if log_format.lower() == "json" else StructuredFormatter()
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

    # Silence overly verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return logging.getLogger("flyio-ai-llm")


logger = logging.getLogger("flyio-ai-llm")
