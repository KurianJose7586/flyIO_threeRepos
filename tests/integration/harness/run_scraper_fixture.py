"""Launch the real scraper service with ONLY the search boundary stubbed.

Everything downstream of the search API — filtering, canonicalisation,
dedup, trust scoring, the per-domain cap, the route, the job queue, the
real crawl4ai crawl, the semantic parser and the chunker — is production
code. Only the outbound HTTP call to a search provider is replaced, since
this container's network policy blocks it.

Hits point at hostnames mapped to the local fixture server in /etc/hosts,
so the trusted-domain ranking and auto-selection path is genuinely
exercised rather than sidestepped.
"""
import os
import sys

# harness/ -> integration/ -> tests/ -> repo root
REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
SERVICE_ROOT = os.path.join(REPO_ROOT, "flyio-scraper-service")
if not os.path.isdir(os.path.join(SERVICE_ROOT, "src")):
    raise SystemExit(f"Cannot find the scraper service at {SERVICE_ROOT}")
sys.path.insert(0, SERVICE_ROOT)
os.chdir(SERVICE_ROOT)

from src.discovery import providers
from src.discovery.queries import extract_destination


async def fake_search(self, query: str, max_results: int):
    dest = extract_destination(query) or query.split()[0]
    hits = [
        # Trusted, tier 1 — must rank first and be auto-selected.
        {"url": f"http://en.wikivoyage.org/wiki/{dest}",
         "title": f"{dest} – Travel guide at Wikivoyage"},
        # Trusted publisher, second tier. Same fixture content; exists to
        # prove the per-domain cap and multi-domain selection.
        {"url": f"http://www.holidify.com/wiki/{dest}",
         "title": f"{dest} Tourism"},
        # Denied — must never reach the crawl.
        {"url": f"https://www.pinterest.com/search/pins/?q={dest}",
         "title": f"{dest} ideas"},
        # Unknown domain — must be listed but never auto-crawled.
        {"url": f"https://some-blog.example/{dest}-trip",
         "title": f"My {dest} trip"},
        # Duplicate of the first with tracking noise — must collapse to one.
        {"url": f"http://en.wikivoyage.org/wiki/{dest}?utm_source=test#See",
         "title": f"{dest} duplicate"},
    ]
    return [{**h, "query": query} for h in hits[:max_results]]


providers.MockProvider.search = fake_search

import uvicorn  # noqa: E402

uvicorn.run("src.main:app", host="127.0.0.1", port=8099, log_level="warning")
