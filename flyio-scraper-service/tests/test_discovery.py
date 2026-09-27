"""Tests for destination -> candidate URL discovery.

No network anywhere: provider HTTP is served by httpx.MockTransport, and the
route tests run against the offline MockProvider that ships as the default
SEARCH_PROVIDER. These cover the filtering rules, which are the part that
decides whether the automated pipeline ingests encyclopaedia pages or SEO
spam — see src/discovery/filters.py.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from src.config.settings import get_settings
from tests.conftest import wait_for_job
from src.discovery.filters import (
    DEFAULT_SCORE,
    Candidate,
    build_candidates,
    canonicalize_url,
    cap_candidates,
    is_crawlable,
    is_denied,
    registrable_domain,
    score_domain,
)
from src.discovery.providers import (
    BraveProvider,
    MockProvider,
    SearchError,
    TavilyProvider,
    get_provider,
    search_all,
)
from src.discovery.queries import (
    InvalidDestinationError,
    build_queries,
    extract_destination,
    normalize_destination,
)


# ── queries ───────────────────────────────────────────────────────────────────

def test_build_queries_covers_every_template():
    """One query per topic — the section spread the chunker produces depends
    on it, so a shrunk template list is a silent quality regression."""
    queries = build_queries("Jabalpur")
    assert len(queries) == 5
    assert all("Jabalpur" in q for q in queries)
    assert len(set(queries)) == 5


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("  Jabalpur  ", "Jabalpur"),
        ("New   Delhi", "New Delhi"),
        # Operators go too, not just quotes — "=" is outside \w.
        ("Jabalpur\" OR 1=1", "Jabalpur OR 1 1"),
        ("Coorg (Kodagu)", "Coorg Kodagu"),
    ],
)
def test_normalize_destination_strips_query_syntax(raw: str, expected: str):
    """Destination text reaches an outbound search URL, so quotes and
    operators are dropped rather than escaped."""
    assert normalize_destination(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", "!!!", "\"\"\""])
def test_normalize_destination_rejects_empty_result(bad: str):
    """A destination that sanitises away to nothing must fail loudly instead
    of searching for the empty string."""
    with pytest.raises(InvalidDestinationError):
        normalize_destination(bad)


def test_extract_destination_round_trips_every_template():
    for query in build_queries("New Delhi"):
        assert extract_destination(query) == "New Delhi"


def test_extract_destination_returns_none_for_unknown_query():
    assert extract_destination("unrelated text") is None


# ── canonicalisation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        # Fragment and tracking parameters identify a visit, not a document.
        ("https://a.com/p?utm_source=x#top", "https://a.com/p"),
        ("https://a.com/p?fbclid=123", "https://a.com/p"),
        ("https://a.com/p?gclid=1&id=7", "https://a.com/p?id=7"),
        # Meaningful params are kept, but sorted so ordering cannot split one
        # page into two candidates.
        ("https://a.com/p?b=2&a=1", "https://a.com/p?a=1&b=2"),
        # Cosmetic differences that must not survive.
        ("HTTPS://A.com/p/", "https://a.com/p"),
        ("https://a.com:443/p", "https://a.com/p"),
        # A bare root keeps its slash — stripping it yields a pathless URL.
        ("https://a.com/", "https://a.com/"),
    ],
)
def test_canonicalize_url(raw: str, expected: str):
    assert canonicalize_url(raw) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://en.wikivoyage.org/wiki/X", "wikivoyage.org"),
        ("https://www.holidify.com/a", "holidify.com"),
        ("https://example.com", "example.com"),
        # Two-label suffix: every state board would otherwise share one
        # per-domain budget under "gov.in".
        ("https://mp.gov.in/x", "mp.gov.in"),
        ("https://tourism.mp.gov.in/x", "mp.gov.in"),
        ("https://a.b.co.uk/p", "b.co.uk"),
        ("not a url", ""),
    ],
)
def test_registrable_domain(url: str, expected: str):
    assert registrable_domain(url) == expected


# ── crawlability, scoring, denial ────────────────────────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/x",     # rejected by POST /scrape/urls too
        "example.com/x",           # no scheme
        "https://",                # no host
        "https://a.com/doc.pdf",   # not a document the parser can chunk
        "https://a.com/img.JPEG",  # extension check is case-insensitive
    ],
)
def test_is_crawlable_rejects(url: str):
    assert is_crawlable(url) is False


def test_is_crawlable_accepts_ordinary_page():
    assert is_crawlable("https://en.wikivoyage.org/wiki/Jabalpur") is True


def test_score_domain_ranks_encyclopaedic_above_publisher_above_unknown():
    wikivoyage, _ = score_domain("wikivoyage.org")
    holidify, _ = score_domain("holidify.com")
    unknown, unknown_trusted = score_domain("some-blog.example")
    assert wikivoyage > holidify > unknown
    assert unknown == DEFAULT_SCORE
    assert unknown_trusted is False


def test_score_domain_trusts_any_government_tourism_board():
    """There are dozens of state boards; listing each one by hand would mean
    a code change per state."""
    score, trusted = score_domain("tourism.rajasthan.gov.in")
    assert trusted is True
    assert score > DEFAULT_SCORE


def test_is_denied_matches_subdomains_and_extra_list():
    assert is_denied("pinterest.com") is True
    assert is_denied("in.pinterest.com") is True
    assert is_denied("wikivoyage.org") is False
    # Deployment-specific additions, from DISCOVERY_DENIED_DOMAINS.
    assert is_denied("spam.example", extra_denied={"spam.example"}) is True


# ── candidate building ────────────────────────────────────────────────────────

def _hit(url: str, title: str = "t", query: str = "q") -> dict:
    return {"url": url, "title": title, "query": query}


def test_build_candidates_drops_denied_and_uncrawlable():
    hits = [
        _hit("https://en.wikivoyage.org/wiki/Jabalpur"),
        _hit("https://www.pinterest.com/search/pins/?q=jabalpur"),
        _hit("https://quora.com/What-is-Jabalpur"),
        _hit("https://a.com/brochure.pdf"),
        _hit("ftp://a.com/x"),
    ]
    urls = [c.url for c in build_candidates(hits)]
    assert urls == ["https://en.wikivoyage.org/wiki/Jabalpur"]


def test_build_candidates_deduplicates_across_queries():
    """The same page ranks for several expansion queries. Without collapsing
    them it gets crawled and embedded once per query — which is how the
    existing Jaipur document ended up stored twice."""
    hits = [
        _hit("https://en.wikivoyage.org/wiki/Jabalpur", query="a"),
        _hit("https://en.wikivoyage.org/wiki/Jabalpur?utm_source=b", query="b"),
        _hit("https://en.wikivoyage.org/wiki/Jabalpur#See", query="c"),
    ]
    candidates = build_candidates(hits)
    assert len(candidates) == 1
    # First sighting wins — results arrive in provider rank order.
    assert candidates[0].query == "a"


def test_build_candidates_orders_by_score_then_search_rank():
    hits = [
        _hit("https://some-blog.example/jabalpur"),
        _hit("https://www.holidify.com/places/jabalpur"),
        _hit("https://en.wikivoyage.org/wiki/Jabalpur"),
        _hit("https://another-blog.example/jabalpur"),
    ]
    candidates = build_candidates(hits)
    assert [c.domain for c in candidates] == [
        "wikivoyage.org",
        "holidify.com",
        # Equal scores keep provider order — stable sort, not alphabetical.
        "some-blog.example",
        "another-blog.example",
    ]


def test_build_candidates_marks_unknown_domains_untrusted():
    """Unknown domains are surfaced for review, not silently dropped — the
    operator decides, and `trusted` is what drives pre-selection."""
    candidates = build_candidates([_hit("https://some-blog.example/jabalpur")])
    assert len(candidates) == 1
    assert candidates[0].trusted is False


# ── capping ───────────────────────────────────────────────────────────────────

def _cand(domain: str, score: int = 50) -> Candidate:
    return Candidate(
        url=f"https://{domain}/{score}",
        title="t",
        domain=domain,
        score=score,
        query="q",
        trusted=False,
    )


def test_cap_candidates_enforces_total_budget():
    capped = cap_candidates([_cand(f"d{i}.com") for i in range(20)], 5, 3)
    assert len(capped) == 5


def test_cap_candidates_enforces_per_domain_limit():
    """Without this the top-scoring site takes every slot and the topic
    spread the query expansion exists to create is lost."""
    crowd = [
        Candidate(f"https://wikivoyage.org/{i}", "t", "wikivoyage.org", 100, "q", True)
        for i in range(10)
    ]
    capped = cap_candidates(crowd + [_cand("holidify.com", 65)], max_urls=6, max_per_domain=2)
    assert [c.domain for c in capped] == ["wikivoyage.org", "wikivoyage.org", "holidify.com"]


# ── providers ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tavily_provider_parses_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(
            200,
            json={"results": [{"url": "https://a.com/x", "title": "A", "content": "…"}]},
        )

    provider = TavilyProvider("k", transport=httpx.MockTransport(handler))
    hits = await provider.search("Jabalpur travel guide", 5)
    assert hits == [
        {"url": "https://a.com/x", "title": "A", "query": "Jabalpur travel guide"}
    ]


@pytest.mark.asyncio
async def test_brave_provider_parses_nested_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "k"
        return httpx.Response(
            200, json={"web": {"results": [{"url": "https://a.com/x", "title": "A"}]}}
        )

    provider = BraveProvider("k", transport=httpx.MockTransport(handler))
    hits = await provider.search("q", 5)
    assert hits == [{"url": "https://a.com/x", "title": "A", "query": "q"}]


@pytest.mark.parametrize("name", ["tavily", "brave"])
def test_provider_without_key_fails_with_actionable_message(name: str):
    """A missing key must not surface as an empty result set — that reads as
    'no pages exist for this destination'."""
    with pytest.raises(SearchError) as exc:
        get_provider(name, "")
    assert "SEARCH_API_KEY" in str(exc.value)


def test_get_provider_rejects_unknown_name():
    with pytest.raises(SearchError):
        get_provider("google", "k")


def test_mock_provider_needs_no_key():
    assert isinstance(get_provider("mock", ""), MockProvider)


@pytest.mark.asyncio
async def test_mock_provider_uses_destination_not_first_word():
    """"things to do in Jabalpur" must not yield /wiki/Things."""
    hits = await MockProvider().search("things to do in Jabalpur", 5)
    assert any("Jabalpur" in h["url"] for h in hits)


@pytest.mark.asyncio
async def test_search_all_survives_one_failing_query():
    """One provider hiccup on a single topic must not discard the other four."""

    class Flaky:
        name = "flaky"

        async def search(self, query: str, max_results: int) -> list[dict]:
            if "stay" in query:
                raise httpx.ConnectTimeout("boom")
            return [_hit(f"https://a.com/{query.split()[0]}", query=query)]

    queries = build_queries("Jabalpur")
    hits, errors = await search_all(Flaky(), queries, 5)
    assert len(hits) == len(queries) - 1
    assert len(errors) == 1
    assert "ConnectTimeout" in errors[0]


# ── POST /scrape/discover ─────────────────────────────────────────────────────

def test_discover_requires_api_key(client: TestClient):
    response = client.post(
        "/scrape/discover",
        json={"destination": "Jabalpur"},
        headers={"X-Service-API-Key": ""},
    )
    assert response.status_code == 401


def test_discover_returns_ranked_candidates(client: TestClient):
    response = client.post("/scrape/discover", json={"destination": "Jabalpur"})
    assert response.status_code == 200
    body = response.json()

    assert body["destination"] == "Jabalpur"
    assert body["provider"] == "mock"
    assert len(body["queries"]) == 5
    # considered counts raw hits; candidates are what survived filtering.
    assert body["considered"] > len(body["candidates"])
    assert body["errors"] == []

    scores = [c["score"] for c in body["candidates"]]
    assert scores == sorted(scores, reverse=True)
    # The denied domain the mock deliberately emits never reaches the caller.
    assert not any("pinterest" in c["url"] for c in body["candidates"])
    # And the unknown domain it emits does, marked for review.
    assert any(c["trusted"] is False for c in body["candidates"])


@pytest.mark.asyncio
async def test_discover_candidates_are_accepted_by_scrape_urls(client: TestClient, monkeypatch):
    """The contract that makes the automation work: every URL discovery
    returns must pass the validation POST /scrape/urls applies, or the
    handoff 400s on candidates this service itself produced.

    The crawl is mocked and the job drained before returning. Unmocked, this
    queued a real browser crawl on the session-wide serial worker: invisible
    where no browser can launch (it failed instantly), but wherever one can,
    it tried the real network and every later test that waits on a job timed
    out queued behind it.
    """

    async def fake_crawl(urls):
        return []

    monkeypatch.setattr("src.queue.worker.run_crawl_urls", fake_crawl)

    candidates = client.post(
        "/scrape/discover", json={"destination": "Jabalpur"}
    ).json()["candidates"]
    assert candidates

    response = client.post(
        "/scrape/urls", json={"urls": [c["url"] for c in candidates]}
    )
    assert response.status_code == 202
    job = await wait_for_job(client, response.json()["job_id"])
    assert job["status"] == "success"


def test_discover_respects_max_urls(client: TestClient):
    body = client.post(
        "/scrape/discover", json={"destination": "Jabalpur", "max_urls": 2}
    ).json()
    assert len(body["candidates"]) <= 2


@pytest.mark.parametrize("bad", [{"destination": "x"}, {"destination": ""}, {}])
def test_discover_rejects_unusable_destination(client: TestClient, bad: dict):
    assert client.post("/scrape/discover", json=bad).status_code == 422


def test_discover_without_search_key_returns_400(client: TestClient, monkeypatch):
    """Misconfiguration is the caller's to fix and must not look like an
    empty result set."""
    settings = get_settings()
    monkeypatch.setattr(settings, "SEARCH_PROVIDER", "tavily")
    monkeypatch.setattr(settings, "SEARCH_API_KEY", "")

    response = client.post("/scrape/discover", json={"destination": "Jabalpur"})
    assert response.status_code == 400
    assert "SEARCH_API_KEY" in response.json()["detail"]


def test_discover_returns_502_when_every_query_fails(client: TestClient, monkeypatch):
    """A dead upstream is not 'nothing found' — reporting zero candidates
    would send someone hunting the wrong problem."""

    class Dead:
        name = "dead"

        async def search(self, query: str, max_results: int) -> list[dict]:
            raise httpx.ConnectError("upstream down")

    monkeypatch.setattr("src.discovery.service.get_provider", lambda *a, **k: Dead())

    response = client.post("/scrape/discover", json={"destination": "Jabalpur"})
    assert response.status_code == 502
    assert "search queries failed" in response.json()["detail"]
