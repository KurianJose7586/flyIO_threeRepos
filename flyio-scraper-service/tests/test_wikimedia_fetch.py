"""Wiki URLs are fetched through the MediaWiki parse API, not a browser.

No network: the API is served by httpx.MockTransport with the documented
action=parse response shape (formatversion=2).
"""

import httpx
import pytest

from src.crawler import wrapper
from src.crawler.wikimedia_fetch import WikiPageMissing, fetch_wiki_page, wiki_article_title

ARTICLE_HTML = (
    '<div class="mw-parser-output"><p>Kochi is a city in Kerala.</p>'
    "<h2>Get in</h2><p>Cochin International Airport serves the city.</p>"
    "<h2>See</h2><ul><li>Fort Kochi</li><li>Mattancherry Palace</li></ul></div>"
)


def _parse_response(title="Kochi", html=ARTICLE_HTML):
    return {"parse": {"title": title, "pageid": 1, "displaytitle": f"<span>{title}</span>", "text": html}}


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://en.wikivoyage.org/wiki/Kochi", ("https://en.wikivoyage.org/w/api.php", "Kochi")),
        ("https://en.wikivoyage.org/wiki/Kochi_(Shikoku)", ("https://en.wikivoyage.org/w/api.php", "Kochi (Shikoku)")),
        ("https://en.wikivoyage.org/wiki/Kochi_%28Shikoku%29", ("https://en.wikivoyage.org/w/api.php", "Kochi (Shikoku)")),
        ("https://en.wikipedia.org/wiki/S%C3%A3o_Paulo", ("https://en.wikipedia.org/w/api.php", "São Paulo")),
        ("https://de.wikivoyage.org/wiki/Kochi", ("https://de.wikivoyage.org/w/api.php", "Kochi")),
        ("http://en.wikivoyage.org/wiki/Kochi", ("http://en.wikivoyage.org/w/api.php", "Kochi")),
    ],
)
def test_recognises_wiki_article_urls(url, expected):
    assert wiki_article_title(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.keralatourism.org/destination/kochi",
        "https://en.wikivoyage.org/wiki/Talk:Kochi",
        "https://en.wikivoyage.org/wiki/Special:Search",
        "https://en.wikivoyage.org/w/index.php?title=Kochi",
        "https://en.wikivoyage.org/wiki/Kochi?action=edit",
        "https://en.wikivoyage.org/wiki/",
        "https://en.m.wikivoyage.org/wiki/Kochi",
        "https://en.wikivoyage.org.evil.test/wiki/Kochi",
        "ftp://en.wikivoyage.org/wiki/Kochi",
    ],
)
def test_other_urls_are_not_wiki_articles(url):
    assert wiki_article_title(url) is None


def test_fetches_article_body_and_keeps_submitted_url():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=_parse_response())

    url = "https://en.wikivoyage.org/wiki/Kochi"
    page = fetch_wiki_page(url, "flyio-test/1.0 (ops@example.test)", transport=httpx.MockTransport(handler))

    assert page == {"title": "Kochi", "url": url, "html": ARTICLE_HTML}
    (req,) = seen
    assert req.url.host == "en.wikivoyage.org" and req.url.path == "/w/api.php"
    assert req.url.params["action"] == "parse"
    assert req.url.params["page"] == "Kochi"
    assert req.url.params["redirects"] == "1"
    assert req.headers["User-Agent"] == "flyio-test/1.0 (ops@example.test)"


def test_never_served_from_a_cache():
    """A re-crawl must see the article as it is now."""
    versions = iter(["<p>old</p>", "<p>new</p>"])

    def handler(request):
        return httpx.Response(200, json=_parse_response(html=next(versions)))

    t = httpx.MockTransport(handler)
    url = "https://en.wikivoyage.org/wiki/Kochi"
    assert fetch_wiki_page(url, "ua", transport=t)["html"] == "<p>old</p>"
    assert fetch_wiki_page(url, "ua", transport=t)["html"] == "<p>new</p>"


def test_missing_article_raises_page_missing():
    def handler(request):
        return httpx.Response(200, json={"error": {"code": "missingtitle", "info": "The page you specified doesn't exist."}})

    with pytest.raises(WikiPageMissing, match="doesn't exist"):
        fetch_wiki_page("https://en.wikivoyage.org/wiki/Nowhere", "ua", transport=httpx.MockTransport(handler))


def test_retries_rate_limit_then_succeeds():
    responses = iter([httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(503), httpx.Response(200, json=_parse_response())])
    sleeps = []
    page = fetch_wiki_page(
        "https://en.wikivoyage.org/wiki/Kochi", "ua",
        transport=httpx.MockTransport(lambda r: next(responses)), sleep=sleeps.append,
    )
    assert page["title"] == "Kochi"
    assert sleeps == [3.0, 2.0]


def test_gives_up_after_three_attempts():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    with pytest.raises(httpx.HTTPStatusError):
        fetch_wiki_page("https://en.wikivoyage.org/wiki/Kochi", "ua", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert len(calls) == 3


# ── run_crawl_urls routing ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wiki_urls_skip_the_browser_and_others_use_it(monkeypatch):
    fetched, browsed = [], []

    def fake_fetch(url):
        fetched.append(url)
        return {"title": "Kochi", "url": url, "html": ARTICLE_HTML}

    def fake_browser(cfg):
        browsed.extend(cfg["start_urls"])
        return [{"title": "Kerala Tourism", "url": u, "html": "<html><body><h1>Kochi</h1><p>Queen of the Arabian Sea, a port city.</p></body></html>"} for u in cfg["start_urls"]]

    monkeypatch.setattr(wrapper, "_fetch_wiki_page", fake_fetch)
    monkeypatch.setattr(wrapper, "_crawl_crawl4ai_source", fake_browser)

    wiki = "https://en.wikivoyage.org/wiki/Kochi"
    other = "https://www.keralatourism.org/destination/kochi"
    chunks = await wrapper.run_crawl_urls([wiki, other])

    assert fetched == [wiki]
    assert browsed == [other]
    assert {c["source_url"] for c in chunks} == {wiki, other}
    assert any("Cochin International Airport" in c["content_text"] for c in chunks)


@pytest.mark.asyncio
async def test_api_failure_falls_back_to_browser(monkeypatch):
    browsed = []

    def failing_fetch(url):
        raise httpx.ConnectError("blocked")

    def fake_browser(cfg):
        browsed.extend(cfg["start_urls"])
        return []

    monkeypatch.setattr(wrapper, "_fetch_wiki_page", failing_fetch)
    monkeypatch.setattr(wrapper, "_crawl_crawl4ai_source", fake_browser)
    await wrapper.run_crawl_urls(["https://en.wikipedia.org/wiki/Kochi"])
    assert browsed == ["https://en.wikipedia.org/wiki/Kochi"]


@pytest.mark.asyncio
async def test_missing_article_is_not_retried_in_the_browser(monkeypatch):
    def missing(url):
        raise WikiPageMissing("gone")

    def browser(cfg):
        raise AssertionError("browser should not be used")

    monkeypatch.setattr(wrapper, "_fetch_wiki_page", missing)
    monkeypatch.setattr(wrapper, "_crawl_crawl4ai_source", browser)
    assert await wrapper.run_crawl_urls(["https://en.wikivoyage.org/wiki/Nowhere"]) == []
