"""
Web search backends.

Free, no key:
  wikimedia   — Wikivoyage + Wikipedia search API. Official and stable.
  duckduckgo  — web-wide via the `ddgs` library. Unofficial; can throttle.
  searxng     — web-wide via a SearXNG instance you run (one container).
Paid, API key: tavily, brave. Offline, synthetic: mock.
Several can be combined, e.g. SEARCH_PROVIDER=wikimedia,duckduckgo.

None of them scrape a search results page directly: that means CAPTCHAs,
IP blocks and a parser that breaks whenever the markup changes.

Each provider takes a query and returns raw hits; all filtering, scoring and
capping happens afterwards in filters.py, so providers stay swappable.
"""
from __future__ import annotations

import asyncio
from typing import Protocol
from urllib.parse import quote

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


# Wikimedia's User-Agent policy asks for a way to reach the operator; the
# project URL serves. Override with SEARCH_USER_AGENT to add an email.
DEFAULT_USER_AGENT = (
    "flyio-scraper-service/1.0 "
    "(+https://github.com/KurianJose7586/flyIO_threeRepos; travel destination discovery)"
)


# Characters MediaWiki leaves unescaped in article URLs, so a title such as
# "Kochi (Shikoku)" links as /wiki/Kochi_(Shikoku) - the form its own pages use
# and people paste - rather than /wiki/Kochi_%28Shikoku%29.
_TITLE_SAFE = "/:;@$!*(),~"


class WikimediaProvider:
    """Wikivoyage + Wikipedia via the MediaWiki search API — free, no key.

    Official, documented and stable, and these two sites are already the top
    of the trust table, so for travel destinations this is the most reliable
    free source there is. It only ever returns those two sites; combine it
    with a web-wide provider ("wikimedia,duckduckgo") for breadth.

    The five topic queries are collapsed to the destination name here: wiki
    full-text search is not a web search engine, and "how to reach Jabalpur
    by train flight bus" matches unrelated railway articles. Each wiki is
    therefore searched once per discovery, not five times.
    """

    name = "wikimedia"
    # (site, result limit). Every Wikivoyage article is a travel guide, so
    # related results (a nearby park, the state) are worth offering. Wikipedia
    # search for a city name also returns its constituency, colleges and
    # railway station, so only its best match — the city article — is taken.
    # None means "use the per-query limit".
    SITES = (("en.wikivoyage.org", None), ("en.wikipedia.org", 1))

    def __init__(
        self,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # Wikimedia rejects requests without a descriptive User-Agent (the
        # crawler hit the same 403 with urllib's default); see
        # https://meta.wikimedia.org/wiki/User-Agent_policy
        self._user_agent = user_agent or DEFAULT_USER_AGENT
        self._transport = transport
        self._pending: dict[str, asyncio.Task] = {}

    async def search(self, query: str, max_results: int) -> list[dict]:
        term = extract_destination(query) or query
        # All five queries arrive together; they share one lookup per term.
        if term not in self._pending:
            self._pending[term] = asyncio.ensure_future(self._search_term(term, max_results))
        hits = await self._pending[term]
        return [{**h, "query": query} for h in hits]

    async def _search_term(self, term: str, max_results: int) -> list[dict]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS,
            transport=self._transport,
            headers={"User-Agent": self._user_agent},
        ) as client:
            results = await asyncio.gather(
                *(
                    self._search_site(client, site, term, limit or max_results)
                    for site, limit in self.SITES
                ),
                return_exceptions=True,
            )
        hits = [
            h
            for r in results
            if not isinstance(r, BaseException)
            for h in self._drop_homonyms(r, term)
        ]
        if not hits:
            failures = [r for r in results if isinstance(r, BaseException)]
            if failures:
                raise failures[0]
        return hits

    @staticmethod
    def _drop_homonyms(hits: list[dict], term: str) -> list[dict]:
        """Drop other places that share the destination's name.

        Wikis name same-named places "Kochi (Shikoku)", "Kochi (prefecture)".
        When the plain "Kochi" article is among the hits it is the one meant,
        so qualified homonyms of it are noise; without it there is no telling
        which one was meant, and all of them are kept.
        """
        key = term.strip().casefold()
        if not any(h["title"].strip().casefold() == key for h in hits):
            return hits
        prefix = key + " ("
        return [h for h in hits if not h["title"].strip().casefold().startswith(prefix)]

    @staticmethod
    async def _search_site(client: httpx.AsyncClient, site: str, term: str, limit: int) -> list[dict]:
        resp = await client.get(
            f"https://{site}/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": term,
                "srlimit": limit,
                "srnamespace": 0,  # articles only, not talk or user pages
                "format": "json",
                "formatversion": 2,
            },
        )
        resp.raise_for_status()
        return [
            {
                "url": f"https://{site}/wiki/{quote(hit['title'].replace(' ', '_'), safe=_TITLE_SAFE)}",
                "title": hit["title"],
            }
            for hit in resp.json().get("query", {}).get("search", [])
            if hit.get("title")
        ]


class DuckDuckGoProvider:
    """Web-wide search through the `ddgs` library — free, no key.

    Unofficial: it queries public search pages rather than a paid API, so it
    can be rate-limited, particularly from datacenter IP ranges. Calls are
    capped at two in flight to avoid tripping that with five topic queries at
    once. Pair it with "wikimedia" so a throttled run still returns the
    most important sources.
    """

    name = "duckduckgo"
    _CONCURRENCY = 2

    def __init__(self, region: str = "in-en", ddgs_factory=None) -> None:
        self._region = region or "in-en"
        # Injection point for tests; production builds a real client.
        self._ddgs_factory = ddgs_factory
        self._slots = asyncio.Semaphore(self._CONCURRENCY)

    def _client(self):
        if self._ddgs_factory is not None:
            return self._ddgs_factory()
        try:
            from ddgs import DDGS  # noqa: PLC0415 — optional dependency
        except ImportError as exc:
            raise SearchError(
                "SEARCH_PROVIDER includes 'duckduckgo' but the ddgs package is not "
                "installed. Run: pip install -r requirements.txt"
            ) from exc
        return DDGS()

    async def search(self, query: str, max_results: int) -> list[dict]:
        async with self._slots:
            # ddgs is synchronous; keep it off the event loop.
            raw = await asyncio.to_thread(
                lambda: self._client().text(query, region=self._region, max_results=max_results)
            )
        return [
            {"url": hit.get("href", ""), "title": hit.get("title", ""), "query": query}
            for hit in raw or []
        ]


class SearxngProvider:
    """A SearXNG instance's JSON API — free, open source, web-wide.

    SearXNG is a metasearch engine you run yourself (one Docker container);
    it queries several engines and needs no API key. The instance must allow
    JSON output: add `json` under `search.formats` in its settings.yml.
    Public instances almost always disable that, so point this at your own.
    """

    name = "searxng"

    def __init__(self, base_url: str, transport: httpx.BaseTransport | None = None) -> None:
        if not base_url:
            raise SearchError(
                "SEARCH_PROVIDER includes 'searxng' but SEARXNG_URL is empty. "
                "Run one with: docker run -d -p 8888:8080 searxng/searxng "
                "and set SEARXNG_URL=http://localhost:8888"
            )
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def search(self, query: str, max_results: int) -> list[dict]:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, transport=self._transport) as client:
            resp = await client.get(
                f"{self._base_url}/search",
                params={"q": query, "format": "json", "language": "en"},
            )
        if resp.status_code == 403:
            raise RuntimeError(
                "SearXNG refused format=json. Enable it: add `json` under "
                "search.formats in the instance's settings.yml, then restart it."
            )
        resp.raise_for_status()
        return [
            {"url": hit.get("url", ""), "title": hit.get("title", ""), "query": query}
            for hit in resp.json().get("results", [])[:max_results]
        ]


class MultiProvider:
    """Runs several providers per query and merges their hits in order.

    One provider failing is not a failed query — its error is kept in
    `partial_errors` for the response, and the others' hits still count. The
    query only fails if every provider does.
    """

    def __init__(self, providers: list) -> None:
        self._providers = providers
        self.name = "+".join(p.name for p in providers)
        self.partial_errors: list[str] = []

    async def search(self, query: str, max_results: int) -> list[dict]:
        results = await asyncio.gather(
            *(p.search(query, max_results) for p in self._providers),
            return_exceptions=True,
        )
        hits: list[dict] = []
        failures: list[BaseException] = []
        for provider, result in zip(self._providers, results):
            if isinstance(result, BaseException):
                failures.append(result)
                self.partial_errors.append(
                    f"{provider.name} on {query!r}: {type(result).__name__}: {result}"
                )
            else:
                hits.extend(result)
        if failures and len(failures) == len(self._providers):
            raise failures[0]
        return hits


_PROVIDER_NAMES = ("wikimedia", "duckduckgo", "searxng", "tavily", "brave", "mock")


def get_provider(
    provider_name: str,
    api_key: str,
    *,
    searxng_url: str = "",
    user_agent: str = DEFAULT_USER_AGENT,
    region: str = "in-en",
) -> SearchProvider:
    """Construct the configured provider, or raise SearchError.

    `provider_name` may list several, comma-separated ("wikimedia,duckduckgo");
    their hits are merged. `api_key` is only used by the paid providers
    (tavily, brave), which is why a list may hold at most one of them.
    """
    names = [n.strip().lower() for n in (provider_name or "").split(",") if n.strip()]
    if not names:
        raise SearchError(f"SEARCH_PROVIDER is empty. Expected one or more of: {', '.join(_PROVIDER_NAMES)}.")
    unknown = [n for n in names if n not in _PROVIDER_NAMES]
    if unknown:
        raise SearchError(
            f"Unknown SEARCH_PROVIDER {', '.join(map(repr, unknown))}. "
            f"Expected one or more of: {', '.join(_PROVIDER_NAMES)}."
        )
    if sum(n in ("tavily", "brave") for n in names) > 1:
        raise SearchError("SEARCH_PROVIDER may include only one of 'tavily' and 'brave' — they share SEARCH_API_KEY.")

    def build(name: str):
        if name == "wikimedia":
            return WikimediaProvider(user_agent)
        if name == "duckduckgo":
            return DuckDuckGoProvider(region)
        if name == "searxng":
            return SearxngProvider(searxng_url)
        if name == "tavily":
            return TavilyProvider(api_key)
        if name == "brave":
            return BraveProvider(api_key)
        return MockProvider()

    # dict.fromkeys drops repeats while keeping the order given.
    providers = [build(n) for n in dict.fromkeys(names)]
    return providers[0] if len(providers) == 1 else MultiProvider(providers)


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
