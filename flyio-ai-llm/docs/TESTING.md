# Testing

```bash
pytest -v
```

111 tests across 20 files. 109 pass with zero setup — no live Qdrant, no Postgres, no API keys needed; the default suite runs entirely against mock providers.

2 tests hit the real Groq API and self-skip unless a key is provided:

```bash
GROQ_API_KEY_FOR_TESTS=gsk_... pytest tests/test_llm_groq_provider.py
```

## CI

Every PR and push to `main` runs the full suite automatically via GitHub Actions (`.github/workflows/tests.yml`) — no secrets required, same reason the local suite doesn't need any.

## What the test suite does and doesn't catch

The suite alone missed a real startup crash once (see git history around the Phase 0 boot-fix commit): the standard test client (`httpx.ASGITransport`) never runs FastAPI's `lifespan`, so a bug only reachable from `lifespan` had no test coverage until a dedicated lifespan-aware test (`tests/test_logging_lifespan.py`) was added. CI catches known regressions; it isn't a substitute for a live boot check when something touches startup, logging config, or middleware ordering.
