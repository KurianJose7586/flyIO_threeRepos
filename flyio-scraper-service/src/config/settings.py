"""
All environment variable reads happen here — nowhere else in the service.
Uses pydantic-settings so every variable is typed, validated, and
documented in one place. Falls back to sane defaults that match the
values already in legacy_crawler/config.py.
"""
import json
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Auth ──────────────────────────────────────────────────────────────────
    # Checked on every /scrape/* request via X-Service-API-Key header.
    SERVICE_API_KEY: str

    # ── Tourism sources ───────────────────────────────────────────────────────
    # Raw JSON string of source config dicts (same shape as config.py SOURCES).
    # Leave empty to use the 6 built-in defaults from legacy_crawler/config.py.
    TOURISM_SOURCES_JSON: str = ""

    # ── Crawler tuning ────────────────────────────────────────────────────────
    # All defaults match legacy_crawler/config.py so behaviour is identical
    # unless you explicitly override via env.
    CRAWL4AI_HEADLESS: bool = True
    CRAWL4AI_PAGE_TIMEOUT_MS: int = 45000
    CRAWL4AI_WAIT_UNTIL: str = "domcontentloaded"
    CRAWL4AI_MAX_CONCURRENT: int = 3
    REQUEST_TIMEOUT: int = 20
    MAX_RETRIES: int = 4
    REQUEST_DELAY_SECONDS: float = 2.0
    REQUEST_DELAY_JITTER: float = 1.0
    RESPECT_ROBOTS_TXT: bool = True

    def get_sources(self) -> list[dict]:
        """
        Returns the list of source config dicts to use for POST /scrape/sources.

        Priority:
          1. TOURISM_SOURCES_JSON env var (JSON array) — if set and non-empty
          2. The 6 built-in defaults in legacy_crawler/config.py SOURCES

        The source dicts must match the shape that crawl4ai_crawler.py and
        wikivoyage_api.py expect:
          {"name": str, "strategy": "crawl4ai"|"mediawiki_api",
           "start_urls": [...], "allowed_domain": str, "max_pages": int}
        """
        if self.TOURISM_SOURCES_JSON.strip():
            return json.loads(self.TOURISM_SOURCES_JSON)
        # Fall back to the existing config — zero hardcoding here
        from legacy_crawler.config import SOURCES  # noqa: PLC0415
        return list(SOURCES)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — settings are parsed once at startup."""
    return Settings()
