"""Boundary, volume and hostile-input tests for destination discovery.

Where test_discovery.py checks that each rule works, this file checks where
the rules stop: input size limits, non-Latin destinations, result volumes
far past the caps, total and partial provider failure, and URLs built to
turn the crawler against the network it runs in.
"""

import asyncio
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from src.discovery.filters import (
    MAX_URL_LENGTH,
    build_candidates,
    canonicalize_url,
    cap_candidates,
    is_crawlable,
)
from src.discovery.providers import search_all
from src.discovery.queries import (
    InvalidDestinationError,
    build_queries,
    normalize_destination,
)


class _FixedProvider:
    """Provider returning a caller-built hit list for every query."""

    name = "fixed"

    def __init__(self, make_hits):
        self._make_hits = make_hits

    async def search(self, query: str, max_results: int) -> list[dict]:
        return [{**h, "query": query} for h in self._make_hits(query)]


def _use_provider(monkeypatch, provider) -> None:
    monkeypatch.setattr("src.discovery.service.get_provider", lambda *a, **k: provider)


# ── request-size boundaries ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "destination, status",
    [("Ab", 200), ("A" * 120, 200), ("A", 422), ("A" * 121, 422)],
)
def test_destination_length_boundaries(client: TestClient, destination: str, status: int):
    """Schema limits are exactly 2..120 characters, inclusive."""
    r = client.post("/scrape/discover", json={"destination": destination})
    assert r.status_code == status


@pytest.mark.parametrize("max_urls, status", [(1, 200), (50, 200), (0, 422), (51, 422), ("ten", 422)])
def test_max_urls_boundaries(client: TestClient, max_urls, status: int):
    r = client.post("/scrape/discover", json={"destination": "Jabalpur", "max_urls": max_urls})
    assert r.status_code == status


def test_max_urls_larger_than_supply_returns_what_exists(client: TestClient):
    """Asking for more than exists is not an error — it returns everything."""
    r = client.post("/scrape/discover", json={"destination": "Jabalpur", "max_urls": 50})
    assert r.status_code == 200
    assert 0 < len(r.json()["candidates"]) < 50


# ── non-Latin and punctuated destinations ────────────────────────────────────

@pytest.mark.parametrize(
    "destination",
    ["São Paulo", "जबलपुर", "Ōsaka", "Mont-Saint-Michel", "L'Aquila", "Hà Nội", "東京"],
)
def test_non_latin_destinations_survive_sanitising(destination: str):
    """India-first product: Devanagari names must reach the search query
    intact, not be stripped as 'unsafe characters'. Relies on \\w being
    Unicode-aware; this pins that."""
    assert normalize_destination(destination) == destination
    assert all(destination in q for q in build_queries(destination))


@pytest.mark.parametrize("destination", ["🏖️🏖️", "!!!", "   ", "​​"])
def test_destination_with_no_letters_is_rejected(destination: str):
    with pytest.raises(InvalidDestinationError):
        normalize_destination(destination)


def test_emoji_around_a_name_is_dropped_not_fatal():
    assert normalize_destination("🏖️ Goa 🌴") == "Goa"


def test_emoji_only_destination_is_a_400_not_a_500(client: TestClient):
    r = client.post("/scrape/discover", json={"destination": "🏖️🏖️"})
    assert r.status_code == 400


# ── result volume ─────────────────────────────────────────────────────────────

def test_ten_thousand_hits_are_capped_quickly():
    """A provider returning far more than asked must still yield at most the
    budget, honour the per-domain cap, and not be slow about it."""
    hits = [
        {"url": f"https://site{i % 500}.example/page/{i}", "title": "t", "query": "q"}
        for i in range(10_000)
    ]
    start = time.perf_counter()
    capped = cap_candidates(build_candidates(hits), max_urls=12, max_per_domain=3)
    elapsed = time.perf_counter() - start

    assert len(capped) == 12
    per_domain: dict[str, int] = {}
    for c in capped:
        per_domain[c.domain] = per_domain.get(c.domain, 0) + 1
    assert max(per_domain.values()) <= 3
    assert elapsed < 1.0, f"filtering 10k hits took {elapsed:.2f}s"


def test_same_page_with_many_tracking_variants_collapses_to_one():
    hits = [
        {"url": f"https://en.wikivoyage.org/wiki/Jabalpur?utm_source=s{i}&utm_medium=m{i}#frag{i}",
         "title": "t", "query": "q"}
        for i in range(200)
    ]
    assert len(build_candidates(hits)) == 1


def test_subdomain_farm_counts_as_one_site():
    """Spam networks mint subdomains to dodge per-site limits."""
    hits = [{"url": f"https://city{i}.spamtravel.com/jabalpur", "title": "t", "query": "q"}
            for i in range(50)]
    capped = cap_candidates(build_candidates(hits), max_urls=12, max_per_domain=3)
    assert len(capped) == 3


def test_all_results_denied_is_an_empty_success_not_an_error(client: TestClient, monkeypatch):
    """A destination where every hit is social/OTA noise is a legitimate
    answer — 200 with nothing kept — not a provider failure."""
    _use_provider(monkeypatch, _FixedProvider(lambda q: [
        {"url": "https://www.pinterest.com/pin/1", "title": "t"},
        {"url": "https://www.booking.com/city/in/jabalpur.html", "title": "t"},
        {"url": "https://www.quora.com/Jabalpur", "title": "t"},
    ]))
    r = client.post("/scrape/discover", json={"destination": "Jabalpur"})
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"] == []
    assert body["considered"] == 15
    assert body["errors"] == []


def test_hits_missing_fields_are_tolerated():
    """Providers occasionally return partial records."""
    hits = [
        {"url": None}, {"title": "no url"}, {},
        {"url": "https://en.wikivoyage.org/wiki/Jabalpur"},  # no title
    ]
    c = build_candidates(hits)
    assert len(c) == 1
    assert c[0].title == c[0].url  # falls back to the URL


# ── provider failure and latency ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_queries_run_concurrently_not_serially():
    """Five queries at 300ms each must take ~300ms, not 1.5s — discovery
    latency is one provider round-trip, not five."""

    class Slow:
        name = "slow"

        async def search(self, query, max_results):
            await asyncio.sleep(0.3)
            return [{"url": "https://a.com/x", "title": "t", "query": query}]

    start = time.perf_counter()
    hits, errors = await search_all(Slow(), build_queries("Jabalpur"), 5)
    elapsed = time.perf_counter() - start
    assert len(hits) == 5 and not errors
    assert elapsed < 0.9, f"took {elapsed:.2f}s — queries are running serially"


def test_every_query_timing_out_is_a_502(client: TestClient, monkeypatch):
    class Timeout:
        name = "timeout"

        async def search(self, query, max_results):
            raise httpx.ReadTimeout("provider too slow")

    _use_provider(monkeypatch, Timeout())
    r = client.post("/scrape/discover", json={"destination": "Jabalpur"})
    assert r.status_code == 502
    assert "ReadTimeout" in r.json()["detail"]


def test_four_of_five_queries_failing_still_returns_the_survivor(client: TestClient, monkeypatch):
    class MostlyDown:
        name = "mostly_down"

        async def search(self, query, max_results):
            if not query.endswith("travel guide"):
                raise httpx.HTTPStatusError(
                    "429", request=httpx.Request("GET", "https://x"), response=httpx.Response(429)
                )
            return [{"url": "https://en.wikivoyage.org/wiki/Jabalpur", "title": "t", "query": query}]

    _use_provider(monkeypatch, MostlyDown())
    r = client.post("/scrape/discover", json={"destination": "Jabalpur"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["candidates"]) == 1
    assert len(body["errors"]) == 4  # surfaced, so thin coverage is visible


# ── hostile URLs ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",   # cloud metadata endpoint
        "http://127.0.0.1:8099/scrape/jobs/x",        # this service
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "http://[::1]/x",
        "http://[fd00::1]/x",
        "http://localhost/admin",
        "http://2130706433/",                         # 127.0.0.1 as an integer
        "http://127.1/",                              # short-form loopback
        "http://0x7f000001/",                         # hex-encoded loopback
        "http://flyio-ai-llm.internal:8000/v1/api/store",  # Fly private network
        "http://svc.flycast/",
        "http://printer.local/",
        "http://8.8.8.8/",                            # even public IP literals
    ],
)
def test_internal_and_ip_literal_urls_are_never_candidates(url: str):
    """The scraper fetches from inside the deployment network. A search
    result naming an internal address would turn it into a request-forgery
    tool, so these are dropped outright — not merely left untrusted."""
    assert is_crawlable(url) is False
    assert build_candidates([{"url": url, "title": "t", "query": "q"}]) == []


def test_credentials_are_stripped_from_candidates():
    c = build_candidates([{"url": "https://user:secret@holidify.com/places/jabalpur", "title": "t"}])
    assert c[0].url == "https://holidify.com/places/jabalpur"
    assert "secret" not in c[0].url


def test_userinfo_disguise_shows_the_real_host():
    """'holidify.com@evil.example' names evil.example. It must not display
    or score as the trusted site."""
    c = build_candidates([{"url": "https://holidify.com@evil.example/jabalpur", "title": "t"}])
    assert c[0].domain == "evil.example"
    assert c[0].trusted is False
    assert "holidify" not in c[0].url


def test_overlong_url_is_rejected():
    ok = "https://a.com/" + "x" * (MAX_URL_LENGTH - len("https://a.com/"))
    assert is_crawlable(ok) is True
    assert is_crawlable(ok + "x") is False


@pytest.mark.parametrize("url", ["https://a.com:99999/x", "https://a.com:abc/x", "http://[::1/x"])
def test_malformed_urls_are_rejected_not_raised(url: str):
    assert is_crawlable(url) is False


def test_non_default_port_is_kept_default_port_dropped():
    assert canonicalize_url("https://a.com:8443/p") == "https://a.com:8443/p"
    assert canonicalize_url("https://a.com:443/p") == "https://a.com/p"


def test_idn_host_is_kept():
    assert is_crawlable("https://münchen.de/reisen") is True


@pytest.mark.parametrize(
    "destination",
    ["दिल्ली", "வாரணாசி", "কলকাতা", "ಮೈಸೂರು", "ഗോവ"],  # Delhi, Varanasi, Kolkata, Mysuru, Goa
)
def test_indic_scripts_keep_their_vowel_signs(destination: str):
    """Indic vowels and viramas are combining marks. They must survive, or
    the name is split mid-word and the search query is meaningless."""
    assert normalize_destination(destination) == destination


def test_decomposed_and_precomposed_accents_normalise_to_one_query():
    decomposed = "São Paulo"   # a + combining tilde
    assert normalize_destination(decomposed) == normalize_destination("São Paulo")


def test_combining_marks_alone_are_not_a_destination():
    with pytest.raises(InvalidDestinationError):
        normalize_destination("ुु")
