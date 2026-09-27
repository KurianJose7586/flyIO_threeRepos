"""Tests for the free search providers and provider combination.

No network: Wikimedia and SearXNG are served by httpx.MockTransport using
the response shapes their APIs document, and DuckDuckGo's `ddgs` client is
replaced with a fake returning the {title, href, body} records it yields.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from src.config.settings import get_settings
from src.discovery.providers import (
    DuckDuckGoProvider,
    MockProvider,
    MultiProvider,
    SearchError,
    SearxngProvider,
    WikimediaProvider,
    get_provider,
    search_all,
)
from src.discovery.queries import build_queries


def _wiki_search(*titles, request=None):
    """MediaWiki `list=search` response, formatversion=2. Honours srlimit
    when given the request, as the real API does."""
    if request is not None:
        titles = titles[: int(request.url.params["srlimit"])]
    return {"batchcomplete": True, "query": {"search": [{"ns": 0, "title": t, "pageid": i} for i, t in enumerate(titles)]}}


# ── Wikimedia ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wikimedia_searches_both_wikis_once_for_all_five_queries():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "en.wikivoyage.org":
            return httpx.Response(200, json=_wiki_search("Jabalpur", "Bhedaghat", request=request))
        return httpx.Response(200, json=_wiki_search("Jabalpur", "Jabalpur Lok Sabha constituency", request=request))

    provider = WikimediaProvider(transport=httpx.MockTransport(handler))
    hits, errors = await search_all(provider, build_queries("Jabalpur"), 5)

    assert not errors
    # One request per wiki, not one per wiki per topic query.
    assert sorted(r.url.host for r in calls) == ["en.wikipedia.org", "en.wikivoyage.org"]
    # Searched for the destination, not "how to reach Jabalpur by train…".
    assert all(r.url.params["srsearch"] == "Jabalpur" for r in calls)
    assert all(r.url.params["srnamespace"] == "0" for r in calls)
    # Wikipedia contributes only its best match; Wikivoyage all of its.
    assert {r.url.host: r.url.params["srlimit"] for r in calls} == {
        "en.wikivoyage.org": "5", "en.wikipedia.org": "1",
    }
    urls = {h["url"] for h in hits}
    assert "https://en.wikipedia.org/wiki/Jabalpur" in urls
    assert not any("constituency" in u for u in urls)
    # Every topic query still gets the hits, so provenance stays per query.
    assert len(hits) == 3 * 5


@pytest.mark.asyncio
async def test_wikimedia_builds_canonical_article_urls():
    def handler(request):
        return httpx.Response(200, json=_wiki_search("Kanha National Park", request=request))

    hits = await WikimediaProvider(transport=httpx.MockTransport(handler)).search("Jabalpur travel guide", 5)
    urls = [h["url"] for h in hits]
    assert "https://en.wikivoyage.org/wiki/Kanha_National_Park" in urls
    assert "https://en.wikipedia.org/wiki/Kanha_National_Park" in urls


@pytest.mark.asyncio
async def test_wikimedia_percent_encodes_non_ascii_titles():
    def handler(request):
        return httpx.Response(200, json=_wiki_search("São Paulo"))

    hits = await WikimediaProvider(transport=httpx.MockTransport(handler)).search("São Paulo travel guide", 5)
    assert hits[0]["url"] == "https://en.wikivoyage.org/wiki/S%C3%A3o_Paulo"


@pytest.mark.asyncio
async def test_wikimedia_sends_a_descriptive_user_agent():
    """Wikimedia refuses generic clients; see its User-Agent policy."""
    seen = []

    def handler(request):
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, json=_wiki_search())

    await WikimediaProvider("flyio-test/1.0 (ops@example.test)", transport=httpx.MockTransport(handler)).search("Goa travel guide", 5)
    assert seen and all(ua == "flyio-test/1.0 (ops@example.test)" for ua in seen)


@pytest.mark.asyncio
async def test_wikimedia_one_wiki_down_still_returns_the_other():
    def handler(request):
        if request.url.host == "en.wikipedia.org":
            return httpx.Response(503)
        return httpx.Response(200, json=_wiki_search("Jabalpur"))

    hits = await WikimediaProvider(transport=httpx.MockTransport(handler)).search("Jabalpur travel guide", 5)
    assert [h["url"] for h in hits] == ["https://en.wikivoyage.org/wiki/Jabalpur"]


@pytest.mark.asyncio
async def test_wikimedia_both_wikis_down_is_a_query_failure():
    provider = WikimediaProvider(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        await provider.search("Jabalpur travel guide", 5)


# ── DuckDuckGo ────────────────────────────────────────────────────────────────

class _FakeDDGS:
    calls: list = []

    def text(self, query, region, max_results):
        _FakeDDGS.calls.append((query, region, max_results))
        return [
            {"title": "Jabalpur - Wikivoyage", "href": "https://en.wikivoyage.org/wiki/Jabalpur", "body": "…"},
            {"title": "Things to do", "href": "https://www.holidify.com/places/jabalpur/", "body": "…"},
        ]


@pytest.mark.asyncio
async def test_duckduckgo_maps_ddgs_records_and_passes_region():
    _FakeDDGS.calls = []
    provider = DuckDuckGoProvider(region="in-en", ddgs_factory=_FakeDDGS)
    hits = await provider.search("things to do in Jabalpur", 5)
    assert hits == [
        {"url": "https://en.wikivoyage.org/wiki/Jabalpur", "title": "Jabalpur - Wikivoyage", "query": "things to do in Jabalpur"},
        {"url": "https://www.holidify.com/places/jabalpur/", "title": "Things to do", "query": "things to do in Jabalpur"},
    ]
    assert _FakeDDGS.calls == [("things to do in Jabalpur", "in-en", 5)]


@pytest.mark.asyncio
async def test_duckduckgo_rate_limit_becomes_a_query_error_not_a_crash():
    class Throttled:
        def text(self, *a, **k):
            raise RuntimeError("202 Ratelimit")

    hits, errors = await search_all(DuckDuckGoProvider(ddgs_factory=Throttled), build_queries("Goa"), 5)
    assert hits == [] and len(errors) == 5
    assert "Ratelimit" in errors[0]


@pytest.mark.asyncio
async def test_duckduckgo_limits_calls_in_flight():
    """Five simultaneous topic queries would invite throttling."""
    import threading
    import time

    state = {"now": 0, "peak": 0}
    lock = threading.Lock()

    class Slow:
        def text(self, *a, **k):
            with lock:
                state["now"] += 1
                state["peak"] = max(state["peak"], state["now"])
            time.sleep(0.05)
            with lock:
                state["now"] -= 1
            return []

    await search_all(DuckDuckGoProvider(ddgs_factory=Slow), build_queries("Goa"), 5)
    assert state["peak"] <= DuckDuckGoProvider._CONCURRENCY


# ── SearXNG ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_searxng_parses_json_results():
    def handler(request):
        assert request.url.path == "/search"
        assert request.url.params["format"] == "json"
        return httpx.Response(200, json={"results": [
            {"url": "https://en.wikivoyage.org/wiki/Goa", "title": "Goa", "engine": "duckduckgo"},
        ]})

    hits = await SearxngProvider("http://localhost:8888/", transport=httpx.MockTransport(handler)).search("Goa travel guide", 5)
    assert hits == [{"url": "https://en.wikivoyage.org/wiki/Goa", "title": "Goa", "query": "Goa travel guide"}]


@pytest.mark.asyncio
async def test_searxng_json_disabled_explains_the_fix():
    """The default SearXNG config serves HTML only and answers 403."""
    provider = SearxngProvider("http://localhost:8888", transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    with pytest.raises(RuntimeError, match="settings.yml"):
        await provider.search("Goa travel guide", 5)


def test_searxng_without_url_explains_setup():
    with pytest.raises(SearchError, match="SEARXNG_URL"):
        get_provider("searxng", "")


# ── get_provider and combination ─────────────────────────────────────────────

def test_free_providers_need_no_key():
    assert isinstance(get_provider("wikimedia", ""), WikimediaProvider)
    assert isinstance(get_provider("duckduckgo", ""), DuckDuckGoProvider)


def test_comma_list_builds_a_combined_provider_in_order():
    p = get_provider(" Wikimedia , duckduckgo ", "")
    assert isinstance(p, MultiProvider)
    assert p.name == "wikimedia+duckduckgo"


def test_repeated_name_is_not_run_twice():
    assert isinstance(get_provider("wikimedia,wikimedia", ""), WikimediaProvider)


@pytest.mark.parametrize("name", ["", " , ", "google", "wikimedia,bing"])
def test_empty_or_unknown_names_are_rejected(name):
    with pytest.raises(SearchError):
        get_provider(name, "")


def test_two_paid_providers_cannot_share_one_key():
    with pytest.raises(SearchError, match="only one"):
        get_provider("tavily,brave", "k")


def test_production_default_is_free_and_real():
    """A fresh deployment returns real results with no configuration."""
    from src.config.settings import Settings
    assert Settings.model_fields["SEARCH_PROVIDER"].default == "wikimedia"


@pytest.mark.asyncio
async def test_combined_provider_keeps_the_survivor_when_one_fails():
    class Down:
        name = "duckduckgo"

        async def search(self, q, n):
            raise RuntimeError("202 Ratelimit")

    multi = MultiProvider([MockProvider(), Down()])
    hits = await multi.search("Jabalpur travel guide", 5)
    assert hits  # mock's hits survive
    assert len(multi.partial_errors) == 1 and "duckduckgo" in multi.partial_errors[0]


@pytest.mark.asyncio
async def test_combined_provider_fails_only_when_all_fail():
    class Down:
        name = "down"

        async def search(self, q, n):
            raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        await MultiProvider([Down(), Down()]).search("q", 5)


def test_partial_provider_failure_is_reported_by_the_route(client: TestClient, monkeypatch):
    """One provider down must not read as a complete result."""
    class Down:
        name = "duckduckgo"

        async def search(self, q, n):
            raise RuntimeError("202 Ratelimit")

    monkeypatch.setattr(
        "src.discovery.service.get_provider",
        lambda *a, **k: MultiProvider([MockProvider(), Down()]),
    )
    r = client.post("/scrape/discover", json={"destination": "Jabalpur"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "mock+duckduckgo"
    assert body["candidates"]
    assert len(body["errors"]) == 5 and all("Ratelimit" in e for e in body["errors"])


def test_route_reports_provider_actually_used(client: TestClient):
    assert client.post("/scrape/discover", json={"destination": "Jabalpur"}).json()["provider"] == "mock"
