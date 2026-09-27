"""
Web search backends.

Search is done through a search API rather than by scraping a search engine
results page. Scraping Google/Bing means CAPTCHAs, IP blocks and a parser that
breaks whenever the markup changes — an unreliable foundation for an automated
pipeline that is supposed to need no attention.

Each provider takes a query and returns raw hits; all filtering, scoring and
capping happens afterwards in filters.py, so providers stay swappable.
"""
from __future__ import annotations

import asyncio
from typing import Protocol

import httpx

from src.discovery.queries import extract_destination

# Per-query timeout. Search APIs answer in well under a second; anything
# slower is a stall, and five queries run concurrently so this is close to the
# whole discovery latency rather than five times it.
_TIMEOUT_SECONDS = 15.0


class SearchError(RuntimeError):
    """Raised when a provider cannot be used at all (missing key, bad config).

    Distinct from a single query failing: that is tolerated and logged, while
    this aborts discovery because no query could ever succeed.
    """


class SearchProvider(Protocol):
    """Anything that can turn a query into raw {url, title, query} hits."""

    name: str

    async def search(self, query: str, max_results: int) -> list[dict]:
        ...


class TavilyProvider:
    """Tavily (https://tavily.com) — search built for retrieval pipelines.

    Returns cleaned page content alongside each hit. This implementation uses
    only the URLs: the crawl path downstream produces section-aware chunks via
    semantic_parser + chunker, which Tavily's flat content field cannot, and
    mixing two chunk shapes in one vector store is what made the existing
    Jaipur document retrieve badly.
    """

    name = "tavily"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        if not api_key:
            raise SearchError(
                "SEARCH_API_KEY is empty but SEARCH_PROVIDER is 'tavily'. "
                "Get a key at https://app.tavily.com or set SEARCH_PROVIDER=mock."
            )
        self._api_key = api_key
        # httpx's own injection point, used only by tests — see
        # tests/test_discovery.py. Production always passes None.
        self._transport = transport

    async def search(self, query: str, max_results: int) -> list[dict]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            resp = await client.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        return [
            {
                "url": hit.get("url", ""),
                "title": hit.get("title", ""),
                "query": query,
            }
            for hit in payload.get("results", [])
        ]


class BraveProvider:
    """Brave Search API — cheapest option; returns links only, no content."""

    name = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str, transport: httpx.BaseTransport | None = None) -> None:
        if not api_key:
            raise SearchError(
                "SEARCH_API_KEY is empty but SEARCH_PROVIDER is 'brave'. "
                "Get a key at https://brave.com/search/api or set SEARCH_PROVIDER=mock."
            )
        self._api_key = api_key
        self._transport = transport

    async def search(self, query: str, max_results: int) -> list[dict]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            resp = await client.get(
                self.endpoint,
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self._api_key,
                },
                params={"q": query, "count": max_results},
            )
            resp.raise_for_status()
            payload = resp.json()

        return [
            {
                "url": hit.get("url", ""),
                "title": hit.get("title", ""),
                "query": query,
            }
            for hit in payload.get("web", {}).get("results", [])
        ]


def _titlecase(slug: str) -> str:
    """Slug -> page-title form: "new-delhi" -> "New_Delhi"."""
    return "_".join(part.capitalize() for part in slug.split("-"))


class MockProvider:
    """Offline provider — no API key, no network, deterministic output.

    Exists so the whole pipeline (route, filtering, ranking, capping, and the
    admin UI on top of it) can be exercised end to end before anyone signs up
    for a search API, and so tests never depend on a live third party. It
    synthesises plausible hits, including denied and unknown domains, so the
    filtering stages are actually exercised rather than bypassed.
    """

    name = "mock"

    async def search(self, query: str, max_results: int) -> list[dict]:
        # Recover the destination from the query rather than guessing at word
        # positions — "things to do in Jabalpur" starts with "things", and a
        # mock that returns /wiki/Things makes the whole demo look broken.
        destination = extract_destination(query) or query
        slug = destination.strip().lower().replace(" ", "-")
        hits = [
            {
                "url": f"https://en.wikivoyage.org/wiki/{_titlecase(slug)}",
                "title": f"{_titlecase(slug)} – Travel guide at Wikivoyage",
            },
            {
                "url": f"https://en.wikipedia.org/wiki/{_titlecase(slug)}",
                "title": f"{_titlecase(slug)} - Wikipedia",
            },
            {
                "url": f"https://www.holidify.com/places/{slug}/",
                "title": f"{_titlecase(slug)} Tourism",
            },
            {
                "url": f"https://www.pinterest.com/search/pins/?q={slug}",
                "title": f"{slug} ideas",  # denied — must be filtered out
            },
            {
                "url": f"https://example-travel-blog.com/{slug}-trip",
                "title": f"My {slug} trip",  # unknown domain — listed, unchecked
            },
        ]
        return [{**h, "query": query} for h in hits[:max_results]]


def get_provider(provider_name: str, api_key: str) -> SearchProvider:
    """Construct the configured provider, or raise SearchError."""
    name = (provider_name or "").strip().lower()
    if name == "tavily":
        return TavilyProvider(api_key)
    if name == "brave":
        return BraveProvider(api_key)
    if name == "mock":
        return MockProvider()
    raise SearchError(
        f"Unknown SEARCH_PROVIDER {provider_name!r}. Expected 'tavily', 'brave' or 'mock'."
    )


async def search_all(
    provider: SearchProvider, queries: list[str], per_query: int
) -> tuple[list[dict], list[str]]:
    """Run every query concurrently and flatten the hits.

    Returns (hits, errors). A query that fails does not abort discovery — one
    provider hiccup on "where to stay in X" should still let the other four
    topics through, with the failure reported so a half-populated result is
    never mistaken for a complete one. Hits keep query order, which
    build_candidates relies on to break score ties by search rank.
    """
    results = await asyncio.gather(
        *(provider.search(q, per_query) for q in queries),
        return_exceptions=True,
    )

    hits: list[dict] = []
    errors: list[str] = []
    for query, result in zip(queries, results):
        if isinstance(result, BaseException):
            errors.append(f"{query!r}: {type(result).__name__}: {result}")
        else:
            hits.extend(result)

    return hits, errors
