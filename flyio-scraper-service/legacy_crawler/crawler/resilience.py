"""
Fallback fetch layer.

Used when Crawl4AI's headless browser can't get a page (blocked, JS
crash, timeout). Two tiers:

  1. Scrapling.Fetcher  — adaptive element matching + stealth headers,
     survives minor anti-bot / markup changes better than plain requests.
  2. Hardened requests.Session — rotating UA, exponential backoff,
     Retry-After handling. Used only if Scrapling isn't installed or
     itself fails, so the pipeline never dies just because one layer
     is unavailable.

Exposes a single function: fetch(url) -> html str | None
"""
import time
import random
import requests

from config import (
    REQUEST_DELAY_SECONDS, REQUEST_DELAY_JITTER, REQUEST_TIMEOUT,
    MAX_RETRIES, BACKOFF_MULTIPLIER, RETRY_STATUS_CODES,
    ROTATE_USER_AGENTS, USER_AGENTS,
)

try:
    from scrapling.fetchers import Fetcher
    _SCRAPLING_AVAILABLE = True
except Exception:
    _SCRAPLING_AVAILABLE = False


def _scrapling_fetch(url: str) -> str | None:
    """Try Scrapling first. Returns None on any failure so the caller
    falls through to the requests-based session below."""
    if not _SCRAPLING_AVAILABLE:
        return None
    try:
        response = Fetcher.get(url, stealthy_headers=True, timeout=REQUEST_TIMEOUT)
        if response is None:
            return None
        # Scrapling's Response exposes the page HTML as `.html_content`
        # (some versions use `.body`) — check both defensively.
        html = getattr(response, "html_content", None) or getattr(response, "body", None)
        status = getattr(response, "status", 200)
        if html and int(status) < 400:
            return html
    except Exception as e:
        print(f"  [scrapling error] {url}: {e}")
    return None


def _build_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
    }


class _ResilientSession:
    """Plain-requests hard fallback: rotating UA, backoff, 429/403 handling."""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(_build_headers())
        self._consecutive_failures = 0

    def get(self, url: str):
        wait = REQUEST_DELAY_SECONDS
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if ROTATE_USER_AGENTS:
                    self._session.headers.update(_build_headers())
                resp = self._session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)

                if resp.status_code == 200:
                    time.sleep(REQUEST_DELAY_SECONDS + random.uniform(0, REQUEST_DELAY_JITTER))
                    return resp

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", wait * 2))
                    print(f"  [429] waiting {retry_after}s")
                    time.sleep(retry_after)
                    continue

                if resp.status_code == 403:
                    self._consecutive_failures += 1
                    print(f"  [403] {url} (attempt {attempt})")
                    if self._consecutive_failures >= 3:
                        self._session = requests.Session()
                        self._session.headers.update(_build_headers())
                        self._consecutive_failures = 0
                    time.sleep(wait * 2)
                    continue

                if resp.status_code in RETRY_STATUS_CODES:
                    print(f"  [{resp.status_code}] retrying {url} in {wait:.1f}s")
                    time.sleep(wait)
                    wait *= BACKOFF_MULTIPLIER
                    continue

                print(f"  [skip {resp.status_code}] {url}")
                return None

            except requests.exceptions.Timeout:
                print(f"  [timeout] {url} attempt {attempt}")
            except requests.exceptions.ConnectionError as e:
                print(f"  [connection error] {url}: {e}")

            time.sleep(wait + random.uniform(0, REQUEST_DELAY_JITTER))
            wait *= BACKOFF_MULTIPLIER

        print(f"  [gave up after {MAX_RETRIES} attempts] {url}")
        return None


_session = _ResilientSession()


def fetch(url: str) -> str | None:
    """Scrapling first, hardened requests session second."""
    html = _scrapling_fetch(url)
    if html:
        return html
    resp = _session.get(url)
    return resp.text if resp else None
