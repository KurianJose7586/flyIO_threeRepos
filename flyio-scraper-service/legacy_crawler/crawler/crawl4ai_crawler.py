"""
Crawl4AI headless-browser crawler for the JS-heavy travel sites
(TourMyIndia, Holidify, Thrillophilia, TravelTriangle, IncredibleIndia).

Deliberately has NO per-site CSS selectors — Crawl4AI's own boilerplate
removal (`result.cleaned_html`) replaces the old hand-written
".entry-content" / ".post-content" selector lists, so this file is
100% generic across every domain in config.SOURCES.

If Crawl4AI itself fails for a URL (browser crash, blocked, timeout),
falls back to crawler.resilience.fetch() (Scrapling -> requests) so a
single flaky page never kills the whole crawl.

If a URL is blocked by robots.txt (e.g. Holidify disallows all
crawlers site-wide), this does NOT scrape the live site around that
block. Instead it tries the Internet Archive's Wayback Machine for a
publicly archived snapshot of that same URL — a separate, legitimate
public archive that isn't subject to the live site's robots.txt. If no
snapshot exists, the URL is skipped, same as before.

Returns raw page dicts: {"title": str, "url": str, "html": str}
"""
import re
import asyncio
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from crawl4ai.async_configs import CacheMode

from config import (
    CRAWL4AI_HEADLESS, CRAWL4AI_PAGE_TIMEOUT_MS, CRAWL4AI_WAIT_UNTIL,
    CRAWL4AI_MAX_CONCURRENT, USER_AGENTS, RESPECT_ROBOTS_TXT,
    EXCLUDE_URL_PATTERNS, REQUEST_TIMEOUT,
)
from crawler.resilience import fetch as fallback_fetch

_robot_cache: dict = {}
_WAYBACK_AVAILABILITY = "https://archive.org/wayback/available"

# Non-page resources that sometimes show up in href attributes (favicons,
# stylesheets, downloads, embedded media) — never worth queueing as a
# "page" to crawl even if a link technically points at one.
_ASSET_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp",
    ".css", ".js", ".json", ".xml", ".rss",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".zip", ".rar", ".mp4", ".mp3", ".webm", ".avi",
)

_ANCHOR_HREF_RE = re.compile(r'<a\s[^>]*?href=["\']([^"\']+)["\']', re.IGNORECASE)


def _is_noise_url(url: str) -> bool:
    """Skip utility/legal/marketing pages that never contain travel content."""
    path = urlparse(url).path.lower()
    return any(pattern in path for pattern in EXCLUDE_URL_PATTERNS)


def _is_asset_url(url: str) -> bool:
    """Skip images/CSS/JS/fonts/downloads — never real page content."""
    path = urlparse(url).path.lower()
    return path.endswith(_ASSET_EXTENSIONS)


def _extract_links(html: str) -> list:
    """Only real <a href="..."> page links — NOT href on <link>, <img>,
    etc. (that regex previously matched favicon/stylesheet hrefs too,
    which is how a PNG ended up queued as a 'page' to crawl)."""
    return _ANCHOR_HREF_RE.findall(html)


def _looks_like_html(content: str) -> bool:
    """Sanity check before handing anything to the HTML parser — catches
    binary/non-HTML responses (e.g. an image fetched by mistake) before
    they get garbage-decoded and parsed as if they were a real page."""
    if not content:
        return False
    head = content[:1000].lower()
    return ("<html" in head or "<body" in head or "<head" in head
            or "<!doctype" in head or "<p" in head or "<div" in head)


def _robots_allowed(url: str, user_agent: str) -> bool:
    if not RESPECT_ROBOTS_TXT:
        return True
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base not in _robot_cache:
        # Fetch robots.txt ourselves with the crawler's UA instead of
        # rp.read(): that uses urllib's default "Python-urllib" UA, which
        # some sites (e.g. all of Wikimedia) answer with 403 — and
        # RobotFileParser treats a 403 as "disallow everything", so every
        # page on the site was skipped even though the real rules allow it.
        # Status handling mirrors RobotFileParser.read().
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            resp = requests.get(base + "/robots.txt", headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT)
            if resp.status_code in (401, 403):
                rp.disallow_all = True
            elif resp.status_code >= 400:
                rp.allow_all = True
            else:
                rp.parse(resp.text.splitlines())
            _robot_cache[base] = rp
        except Exception:
            _robot_cache[base] = None
    rp = _robot_cache[base]
    return True if rp is None else rp.can_fetch(user_agent, url)


def _wayback_snapshot(url: str) -> str | None:
    """
    Looks up the closest archived snapshot of `url` via the Wayback
    Machine's public availability API, then fetches the RAW archived
    HTML (the `id_` modifier strips the Wayback toolbar/JS injection
    so we get back the page's original markup, not archive.org's UI).
    Returns None if no snapshot exists or the lookup fails.
    """
    try:
        resp = requests.get(_WAYBACK_AVAILABILITY, params={"url": url}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        snapshot = (resp.json().get("archived_snapshots") or {}).get("closest")
        if not snapshot or not snapshot.get("available"):
            return None

        snap_url = snapshot["url"]
        m = re.search(r"/web/(\d+)/", snap_url)
        raw_url = snap_url.replace(f"/web/{m.group(1)}/", f"/web/{m.group(1)}id_/") if m else snap_url

        html_resp = requests.get(raw_url, timeout=REQUEST_TIMEOUT)
        if html_resp.status_code == 200 and len(html_resp.text) > 200 and _looks_like_html(html_resp.text):
            return html_resp.text
    except Exception as e:
        print(f"  [wayback error] {url}: {e}")
    return None


def _normalize_url(url: str) -> str:
    p = urlparse(url)
    return p._replace(fragment="").geturl().rstrip("/")


def _same_domain(url: str, allowed: str) -> bool:
    return urlparse(url).netloc == allowed


async def _crawl_async(source_cfg: dict) -> list:
    allowed_domain = source_cfg["allowed_domain"]
    max_pages = source_cfg.get("max_pages", 20)
    user_agent = USER_AGENTS[0]

    browser_cfg = BrowserConfig(headless=CRAWL4AI_HEADLESS, user_agent=user_agent, verbose=False)
    run_cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=CRAWL4AI_PAGE_TIMEOUT_MS,
        wait_until=CRAWL4AI_WAIT_UNTIL,
        exclude_external_links=True,
        word_count_threshold=20,
    )

    queue = [_normalize_url(u) for u in source_cfg["start_urls"]]
    visited: set = set()
    results: list = []
    semaphore = asyncio.Semaphore(CRAWL4AI_MAX_CONCURRENT)

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        while queue and len(results) < max_pages:
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            if not _robots_allowed(url, user_agent):
                print(f"  [robots.txt block] {url} -> trying Wayback Machine archive")
                html = _wayback_snapshot(url)
                if not html:
                    print(f"  [wayback: no snapshot available] {url} -- skipping")
                    continue
                print(f"  [wayback hit] {url} -> using archived snapshot")
                page_title = url
                discovered_links = _extract_links(html)
                results.append({"title": page_title, "url": url, "html": html})
                added = 0
                for href in discovered_links:
                    if added >= 15:
                        break
                    link = urljoin(url, href)
                    norm = _normalize_url(link)
                    if _is_noise_url(norm) or _is_asset_url(norm):
                        continue
                    if _same_domain(link, allowed_domain) and norm not in visited and norm not in queue:
                        queue.append(norm)
                        added += 1
                continue

            print(f"  [{len(results)+1}/{max_pages}] crawl4ai fetching: {url}")
            html, page_title, discovered_links = None, url, []

            try:
                async with semaphore:
                    result = await crawler.arun(url=url, config=run_cfg)
                if result and result.success:
                    html = result.cleaned_html or result.html
                    page_title = (result.metadata or {}).get("title") or url
                    internal = (result.links or {}).get("internal", [])
                    discovered_links = [
                        l.get("href") for l in internal
                        if l.get("href") and not _is_asset_url(l.get("href"))
                    ]
                else:
                    err = getattr(result, "error_message", "unknown") if result else "no result object"
                    print(f"  [crawl4ai failed] {url} -> {err} -- falling back")
            except Exception as e:
                print(f"  [crawl4ai error] {url}: {e} -> falling back")

            if not html:
                # The fallback only swallows timeouts/connection errors itself;
                # anything else (e.g. requests' InvalidURL) must not abort the
                # whole crawl — skip just this URL like any other dead page.
                try:
                    html = fallback_fetch(url)
                except Exception as e:
                    print(f"  [fallback error] {url}: {e}")
                    html = None
                if html:
                    discovered_links = _extract_links(html)
                else:
                    print(f"  [fallback also failed] {url} -- both Crawl4AI and resilience.fetch() returned nothing")

            if not html or len(html) < 200 or not _looks_like_html(html):
                got = len(html) if html else 0
                reason = "not real HTML (likely a binary asset fetched by mistake)" if html and not _looks_like_html(html) \
                    else "likely a bot-block/JS-wall page, or robots.txt blocked it upstream"
                print(f"  [skip: only {got} chars of content] {url} ({reason})")
                continue

            results.append({"title": page_title, "url": url, "html": html})

            added = 0
            for href in discovered_links:
                if added >= 15:
                    break
                link = urljoin(url, href)
                norm = _normalize_url(link)
                if _is_noise_url(norm) or _is_asset_url(norm):
                    continue
                if _same_domain(link, allowed_domain) and norm not in visited and norm not in queue:
                    queue.append(norm)
                    added += 1

    print(f"  Done: {len(results)} pages collected from {source_cfg['name']}")
    return results


def crawl_crawl4ai_source(source_cfg: dict) -> list:
    """Sync wrapper so main.py's orchestrator stays plain synchronous code."""
    return asyncio.run(_crawl_async(source_cfg))
