"""Tests for the two log formatters (app/core/logging.py) — Phase 4.2.

Distinct from tests/test_logging_lifespan.py, which guards against the
setup_logging()/extra={...} collision crash (Phase 0). These tests are
about the *content* of what gets logged: valid JSON per line, and — the
concrete bug this phase fixes — an exception traceback actually appearing
in the output at all, which neither formatter did before this change.
"""

import io
import json
import logging

import pytest

from app.core.logging import JSONFormatter, StructuredFormatter, setup_logging


@pytest.fixture
def captured_log() -> io.StringIO:
    """Redirect the root logger's handler to an in-memory buffer so tests can
    inspect exactly what would have been written to stdout.
    """
    buf = io.StringIO()
    yield buf


def _configure_and_capture(log_format: str, buf: io.StringIO) -> None:
    setup_logging("INFO", log_format)
    for handler in logging.getLogger().handlers:
        handler.stream = buf


def test_json_format_is_valid_json_per_line(captured_log: io.StringIO):
    _configure_and_capture("json", captured_log)
    from app.core.logging import logger

    logger.info("hello", extra={"event": "e1", "request_id": "req_1"})
    logger.warning("world", extra={"event": "e2", "request_id": "req_1"})

    lines = captured_log.getvalue().strip().split("\n")
    assert len(lines) == 2
    for line in lines:
        d = json.loads(line)  # raises if not valid JSON
        assert set(d.keys()) >= {"timestamp", "level", "service", "request_id", "event", "message", "logger"}

    first = json.loads(lines[0])
    assert first["message"] == "hello"
    assert first["event"] == "e1"
    assert first["request_id"] == "req_1"
    assert first["level"] == "INFO"


def test_json_format_includes_exception_traceback(captured_log: io.StringIO):
    """The concrete bug this phase fixes: logger.exception() (used by
    main.py's unhandled_exception_handler) previously produced a log line
    with the traceback silently dropped entirely.
    """
    _configure_and_capture("json", captured_log)
    from app.core.logging import logger

    try:
        raise ValueError("deliberate test error")
    except ValueError:
        logger.exception("boom", extra={"event": "test_exc", "request_id": "req_2"})

    line = captured_log.getvalue().strip()
    d = json.loads(line)
    assert "exception" in d
    assert "ValueError: deliberate test error" in d["exception"]
    assert "Traceback (most recent call last)" in d["exception"]


def test_json_lines_stay_one_line_each_despite_embedded_traceback_newlines(captured_log: io.StringIO):
    """A traceback contains real newlines. If they weren't escaped inside the
    JSON string, one exception log call would corrupt JSONL framing —
    producing multiple broken 'lines' for what should be a single log event,
    which is exactly what a log aggregator tailing this file line-by-line
    would choke on.
    """
    _configure_and_capture("json", captured_log)
    from app.core.logging import logger

    logger.info("before", extra={"event": "e1", "request_id": "req_3"})
    try:
        1 / 0
    except ZeroDivisionError:
        logger.exception("during", extra={"event": "e2", "request_id": "req_3"})
    logger.info("after", extra={"event": "e3", "request_id": "req_3"})

    lines = captured_log.getvalue().strip().split("\n")
    assert len(lines) == 3  # not more — the traceback didn't split into extra "lines"
    for line in lines:
        json.loads(line)  # every line independently parses


def test_text_format_includes_exception_traceback(captured_log: io.StringIO):
    """Same fix, for the LOG_FORMAT=text path — this formatter had the
    identical gap before this phase.
    """
    _configure_and_capture("text", captured_log)
    from app.core.logging import logger

    try:
        raise RuntimeError("text format test error")
    except RuntimeError:
        logger.exception("boom in text mode", extra={"event": "test_exc", "request_id": "req_4"})

    output = captured_log.getvalue()
    assert "RuntimeError: text format test error" in output
    assert "Traceback (most recent call last)" in output
    # Still single-line key=value for the non-exception part, unchanged shape.
    assert "request_id=req_4 event=test_exc message=boom in text mode" in output


def test_text_format_is_not_valid_json():
    """Sanity check the two formatters are genuinely different outputs, not
    the same content with a cosmetic label — text output must NOT parse as
    JSON, or LOG_FORMAT would be a no-op.
    """
    formatter = StructuredFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="x", lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    output = formatter.format(record)
    with pytest.raises(json.JSONDecodeError):
        json.loads(output)


def test_json_format_is_the_default(captured_log: io.StringIO):
    """Settings.LOG_FORMAT defaults to 'json' (see config.py) — confirm
    setup_logging() without an explicit log_format argument matches that
    default, since existing call sites (and tests, e.g.
    test_logging_lifespan.py) call setup_logging(log_level) with only one
    argument.
    """
    setup_logging("INFO")  # no log_format argument
    for handler in logging.getLogger().handlers:
        handler.stream = captured_log
    from app.core.logging import logger

    logger.info("default format check", extra={"event": "e1", "request_id": "req_5"})
    line = captured_log.getvalue().strip()
    json.loads(line)  # must be valid JSON — proves the default is "json", not "text"


def test_settings_log_format_default_is_json():
    from app.core.config import Settings

    assert Settings().LOG_FORMAT == "json"
