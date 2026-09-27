"""
Fetch Wikivoyage / Wikipedia articles through the MediaWiki parse API.

Discovery mostly returns these two wikis, and a headless browser is the wrong
tool for them: Wikimedia rate-limits and challenges automated page loads, and
the browser pays for a full page render to reach HTML the API hands over
directly. The parse API is official, returns the article body only (no site
chrome), and is what the legacy "mediawiki_api" strategy already crawls with.

The legacy fetcher caches every response on disk forever, which suits its
batch job but would make a re-crawl return a stale copy, so this module talks
to the API itself and never caches.

Output matches the crawlers': {"title", "url", "html"}, where "url" is the
URL that was submitted, so chunks and crawl history carry the admin's URL.
"""
from __future__ import annotations

import re
import time
from urllib.parse import unquote, urlsplit

import httpx
from bs4 import BeautifulSoup

# en.wikivoyage.org, de.wikipedia.org, … — not m. (mobile) or other projects.
_WIKI_HOST = re.compile(r"^[a-z][a-z-]*\.(wikivoyage|wikipedia)\.org$")
# Namespaced pages (Talk:, Special:, File:, …) are not articles.
_NAMESPACED = re.compile(r"^[A-Za-z ]+:")

_TIMEOUT_SECONDS = 20.0
_ATTEMPTS = 3
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRY_AFTER_SECONDS = 10.0


class WikiPageMissing(Exception):
    """The wiki answered, and has no such article. Retrying will not help."""


def wiki_article_title(url: str) -> tuple[str, str] | None:
    """(api_endpoint, title) for a wiki article URL, else None.

    "https://en.wikivoyage.org/wiki/Kochi_(Shikoku)"
        -> ("https://en.wikivoyage.org/w/api.php", "Kochi (Shikoku)")
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not _WIKI_HOST.match(host):
        return None
    if not parts.path.startswith("/wiki/") or parts.query:
        return None
    title = unquote(parts.path[len("/wiki/"):]).replace("_", " ").strip()
    # "Delhi/West" is a real Wikivoyage article (a district of Delhi).
    if not title or title.startswith("/") or _NAMESPACED.match(title):
        return None
    # Same scheme as submitted: Wikimedia redirects http to https anyway.
    return f"{parts.scheme}://{host}/w/api.php", title


def fetch_wiki_page(
    url: str,
    user_agent: str,
    transport: httpx.BaseTransport | None = None,
    sleep=time.sleep,
) -> dict:
    """Fetch one article; raises WikiPageMissing or an httpx error on failure."""
    target = wiki_article_title(url)
    if target is None:
        raise ValueError(f"not a wiki article URL: {url}")
    api, title = target
    params = {
        "action": "parse",
        "page": title,
        "prop": "text|displaytitle",
        "redirects": 1,
        "disableeditsection": 1,
        "disabletoc": 1,
        "format": "json",
        "formatversion": 2,
    }
    with httpx.Client(
        timeout=_TIMEOUT_SECONDS,
        transport=transport,
        headers={"User-Agent": user_agent},
        follow_redirects=True,
    ) as client:
        for attempt in range(1, _ATTEMPTS + 1):
            try:
                resp = client.get(api, params=params)
            except httpx.TransportError:
                if attempt == _ATTEMPTS:
                    raise
                sleep(2 ** (attempt - 1))
                continue
            if resp.status_code in _RETRY_STATUSES and attempt < _ATTEMPTS:
                sleep(_retry_delay(resp, attempt))
                continue
            resp.raise_for_status()
            break

    data = resp.json()
    if "error" in data:
        err = data["error"]
        raise WikiPageMissing(f"{title}: {err.get('info') or err.get('code') or 'not found'}")
    parsed = data.get("parse") or {}
    html = parsed.get("text") or ""
    if isinstance(html, dict):  # formatversion=1 shape
        html = html.get("*", "")
    if not html.strip():
        raise WikiPageMissing(f"{title}: empty article")
    display = parsed.get("displaytitle") or parsed.get("title") or title
    return {
        "title": BeautifulSoup(display, "html.parser").get_text(" ", strip=True) or title,
        "url": url,
        "html": html,
    }


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    try:
        wait = float(resp.headers.get("Retry-After", ""))
    except ValueError:
        wait = 2.0 ** (attempt - 1)
    return max(0.0, min(wait, _MAX_RETRY_AFTER_SECONDS))
