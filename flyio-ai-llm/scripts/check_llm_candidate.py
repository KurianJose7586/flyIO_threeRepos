"""Run inside the candidate via stdin; no secret values are printed."""
import asyncio
import json
import time
import sys
import urllib.error
import urllib.request

from app.core.config import get_settings


class CheckFailure(RuntimeError):
    def __init__(self, code):
        self.code = code


def main():
    try:
        cfg = get_settings()
    except Exception:
        raise CheckFailure(10) from None
    if not cfg.SERVICE_API_KEY:
        raise CheckFailure(11)
    llm = cfg.LLM_PROVIDER.lower()
    embedding = cfg.EMBEDDING_PROVIDER.lower()
    if llm not in {"mock", "openai", "groq"} or embedding not in {"mock", "openai", "local"}:
        raise CheckFailure(12)
    if llm != "mock" and not cfg.LLM_API_KEY:
        raise CheckFailure(13)
    if embedding == "openai" and not cfg.EMBEDDING_API_KEY:
        raise CheckFailure(14)
    if cfg.DATABASE_ENABLED and not cfg.DATABASE_URL:
        raise CheckFailure(15)

    def get(path, key=None):
        headers = {"User-Agent": "Flyio-Jenkins-Deploy/1.0"}
        if key is not None:
            headers["X-Service-API-Key"] = key
        req = urllib.request.Request("http://127.0.0.1:8000" + path, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)

    successes = 0
    stage = 20
    for _ in range(30):
        try:
            stage = 20
            if get("/health").get("status") != "healthy":
                raise RuntimeError("Unhealthy service")
            stage = 21
            qdrant = get("/health/qdrant")
            if not qdrant.get("connected") or not qdrant.get("collection_exists"):
                raise RuntimeError("Qdrant collection unavailable")
            stage = 22
            if cfg.DATABASE_ENABLED and not get("/health/postgres").get("connected"):
                raise RuntimeError("PostgreSQL unavailable")
            stage = 23
            probe = cfg.API_V1_STR + "/deployment-readiness"
            for key, expected in ((None, 401), (cfg.SERVICE_API_KEY, 404)):
                try:
                    get(probe, key)
                except urllib.error.HTTPError as exc:
                    if exc.code != expected:
                        raise RuntimeError("Authentication readiness failed") from None
                else:
                    raise RuntimeError("Unexpected authentication response")
            successes += 1
            if successes >= 3:
                break
        except (OSError, ValueError, RuntimeError):
            successes = 0
        time.sleep(3)
    else:
        raise CheckFailure(stage)

    # No paid LLM/embedding calls and no vector writes during deployment.
    # Local embedding check may download model weights on first use. It runs
    # in a separate process, so it does not warm the API process's RAM cache.
    if embedding == "local":
        from app.services.embeddings.service import EmbeddingService
        try:
            vector = asyncio.run(EmbeddingService(settings=cfg).embed_query("Deployment readiness"))
        except Exception:
            raise CheckFailure(24) from None
        if len(vector) != cfg.EMBEDDING_DIMENSION:
            raise CheckFailure(25)


if __name__ == "__main__":
    try:
        main()
    except CheckFailure as exc:
        sys.exit(exc.code)
    except Exception:
        sys.exit(26)
