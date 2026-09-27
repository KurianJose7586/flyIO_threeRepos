"""
Thin async wrapper around legacy_crawler.

This module is the ONLY place in the service that imports from legacy_crawler.
It does NOT change any crawling, parsing, or chunking logic — it only:
  1. Calls the right legacy function based on the source strategy
  2. Offloads all sync calls to a thread pool (run_in_executor) so
     FastAPI's event loop is never blocked during long crawls

Pipeline per page:
  crawl_*_source(source_cfg)
      → list[{"title": str, "url": str, "html": str}]
  parse_page(html, fallback_title)
      → {"title": str, "elements": list[node]}
  chunk_page(page_title, source_url, elements)
      → list[{source_url, page_title, section_path,
               chunk_index, content_text, content_html}]

The final chunk shape is the exact native output of chunker.py —
no field remapping, no transformation.

Each legacy_crawler entry point below is imported lazily, inside its own
small wrapper function, and — importantly — independently of the other
three:
  - _crawl_crawl4ai_source() needs crawl4ai + a Playwright/Chromium install.
  - _crawl_wikivoyage(), _parse_page(), and _chunk_page() only need
    requests/mwparserfromhell/tenacity/bs4 — already required for the
    light FastAPI layer, never crawl4ai.

Splitting them (rather than one lazy import of all four together) means:
  1. Importing this module — and therefore importing the FastAPI app —
     never requires crawl4ai/scrapling/Chromium, so tests and CI runs
     that never touch a real browser (auth middleware, job-status routes,
     the parser/chunker pipeline itself) don't need that toolchain either.
  2. A "mediawiki_api" strategy crawl (Wikivoyage/Wikipedia via their
     official API) genuinely never needs crawl4ai — bundling all four
     imports together used to mean even a pure-API crawl would fail to
     start if crawl4ai/Chromium was missing or broken, for a dependency
     it was never going to use.
See docs/TESTING.md.
"""
import asyncio
import logging
import sys
import os
import warnings

from src.crawler.wikimedia_fetch import WikiPageMissing, fetch_wiki_page, wiki_article_title

logger = logging.getLogger(__name__)

# Suppress a benign BeautifulSoup warning that fires when a URL string
# accidentally gets fed to the HTML parser during title-tag cleaning in
# semantic_parser.py. This is not a bug — the warning is spurious here.
from bs4 import MarkupResemblesLocatorWarning
warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)


def _setup_legacy_path() -> None:
    """Make legacy_crawler importable — idempotent, safe to call before
    every lazy import below.
    """
    # Adds the repo root to sys.path so legacy_crawler.* imports work
    # correctly regardless of where uvicorn is launched from.
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)

    # Also add legacy_crawler itself to sys.path so that legacy modules that do
    # plain `from config import ...` (not `from legacy_crawler.config import ...`)
    # continue to work exactly as they did in the original travel_pipeline folder.
    legacy = os.path.join(root, "legacy_crawler")
    if legacy not in sys.path:
        sys.path.insert(0, legacy)


def _crawl_crawl4ai_source(source_cfg: dict) -> list[dict]:
    """Needs crawl4ai + a Playwright/Chromium install."""
    _setup_legacy_path()
    from legacy_crawler.crawler.crawl4ai_crawler import crawl_crawl4ai_source
    return crawl_crawl4ai_source(source_cfg)


def _crawl_wikivoyage(source_cfg: dict) -> list[dict]:
    """Only needs requests/mwparserfromhell/tenacity/bs4 — never crawl4ai."""
    _setup_legacy_path()
    from legacy_crawler.crawler.wikivoyage_api import crawl_wikivoyage
    return crawl_wikivoyage(source_cfg)


def _parse_page(html: str, fallback_title: str) -> dict:
    """Only needs bs4."""
    _setup_legacy_path()
    from legacy_crawler.parser.semantic_parser import parse_page
    return parse_page(html, fallback_title)


def _chunk_page(page_title: str, source_url: str, elements: list) -> list[dict]:
    """Pure Python — no external dependency beyond the standard library."""
    _setup_legacy_path()
    from legacy_crawler.parser.chunker import chunk_page
    return chunk_page(page_title, source_url, elements)


async def run_crawl_source(source_cfg: dict) -> list[dict]:
    """
    Runs one source config through the full pipeline in a thread pool.

    Args:
        source_cfg: dict matching the shape used by legacy_crawler/config.py SOURCES.
                    Must contain "strategy": "crawl4ai" | "mediawiki_api".

    Returns:
        List of chunk dicts, each with:
          source_url, page_title, section_path, chunk_index,
          content_text, content_html
    """
    loop = asyncio.get_event_loop()
    strategy = source_cfg.get("strategy", "crawl4ai")

    # ── Step 1: Crawl (sync — offloaded so the event loop stays free) ────────
    if strategy == "mediawiki_api":
        pages = await loop.run_in_executor(None, _crawl_wikivoyage, source_cfg)
    else:
        pages = await loop.run_in_executor(None, _crawl_crawl4ai_source, source_cfg)

    # ── Step 2: Parse + chunk each page ──────────────────────────────────────
    return await _parse_and_chunk(pages)


async def _parse_and_chunk(pages: list[dict]) -> list[dict]:
    # parse_page and chunk_page are both synchronous — offload to thread pool.
    # chunk_page natively returns the exact chunk schema we want:
    #   {source_url, page_title, section_path, chunk_index, content_text, content_html}
    loop = asyncio.get_event_loop()
    all_chunks: list[dict] = []
    for page in pages:
        parsed = await loop.run_in_executor(
            None,
            _parse_page,
            page["html"],
            page["title"],   # fallback_title if <title> tag is missing
        )
        chunks = await loop.run_in_executor(
            None,
            _chunk_page,
            parsed["title"],    # page_title  (extracted from <title> or fallback)
            page["url"],        # source_url
            parsed["elements"], # structured nodes from semantic_parser
        )
        all_chunks.extend(chunks)

    return all_chunks


async def run_crawl_urls(urls: list[str]) -> list[dict]:
    """
    Wraps a list of arbitrary URLs as a crawl4ai source config.
    No domain restriction — crawls exactly the URLs provided.

    Args:
        urls: List of fully-qualified URLs to crawl.

    Returns:
        Same chunk schema as run_crawl_source.
    """
    if not urls:
        return []

    # Wikivoyage/Wikipedia articles come from the MediaWiki API; a browser is
    # only used for them if the API itself cannot be reached.
    loop = asyncio.get_event_loop()
    pages: list[dict] = []
    browser_urls: list[str] = []
    for url in urls:
        if wiki_article_title(url) is None:
            browser_urls.append(url)
            continue
        try:
            pages.append(await loop.run_in_executor(None, _fetch_wiki_page, url))
        except WikiPageMissing as exc:
            logger.warning("Wiki article not found, skipping %s: %s", url, exc)
        except Exception as exc:
            logger.warning("MediaWiki API fetch failed for %s (%s); trying the browser", url, exc)
            browser_urls.append(url)

    if browser_urls:
        source_cfg = {
            "name": "custom_urls",
            "strategy": "crawl4ai",
            "start_urls": browser_urls,
            "allowed_domain": None,  # no domain fence — crawl each URL as-is
            "max_pages": len(browser_urls),
        }
        pages.extend(await loop.run_in_executor(None, _crawl_crawl4ai_source, source_cfg))

    return await _parse_and_chunk(pages)


def _fetch_wiki_page(url: str) -> dict:
    from src.config.settings import get_settings
    return fetch_wiki_page(url, get_settings().SEARCH_USER_AGENT)
