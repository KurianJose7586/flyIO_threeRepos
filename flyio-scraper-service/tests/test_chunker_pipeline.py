"""Real (unmocked) test of the parse_page -> chunk_page pipeline.

Deliberately does NOT mock anything here — this is the one test in the
suite proving the actual contract Admin and flyio-ai-llm depend on
(source_url, page_title, section_path, chunk_index, content_text,
content_html) is what the real parser/chunker produce, not just what the
docstrings claim. Uses src.crawler.wrapper's own _parse_page/_chunk_page —
the same lazy-import path production code uses — rather than importing
legacy_crawler directly, so this test also incidentally exercises that
the lazy-import machinery itself works.

Needs only bs4/lxml (already required for the light FastAPI layer) — not
crawl4ai, scrapling, or a browser. Confirmed while writing this: importing
_parse_page/_chunk_page specifically (not the crawl4ai-dependent
_crawl_crawl4ai_source) does NOT require crawl4ai to be installed — see
wrapper.py's module docstring on why the four lazy imports are split
rather than bundled.
"""

from src.crawler.wrapper import _chunk_page as chunk_page
from src.crawler.wrapper import _parse_page as parse_page

SAMPLE_HTML = """
<html>
<head><title>Tokyo Travel Guide</title></head>
<body>
  <h1>Tokyo</h1>
  <p>Tokyo is the capital of Japan and one of the world's most populous cities.</p>
  <h2>See</h2>
  <p>Senso-ji is an ancient Buddhist temple located in Asakusa, founded in 645 AD.</p>
  <p>The Meiji Shrine is dedicated to Emperor Meiji and Empress Shoken.</p>
  <h2>Eat</h2>
  <p>Tsukiji Outer Market has fresh sushi and street food stalls.</p>
</body>
</html>
"""


def test_chunk_page_produces_the_documented_contract_shape():
    parsed = parse_page(SAMPLE_HTML, "Fallback Title")
    chunks = chunk_page(parsed["title"], "https://en.wikivoyage.org/wiki/Tokyo", parsed["elements"])

    assert len(chunks) >= 1
    for chunk in chunks:
        # Exact keys CONTRACT.md and flyio-ai-llm's StoreDocumentItem
        # (pre_chunked mode) assume — an extra or missing key here would
        # silently break that integration.
        assert set(chunk.keys()) == {
            "source_url", "page_title", "section_path",
            "chunk_index", "content_text", "content_html",
        }
        assert chunk["source_url"] == "https://en.wikivoyage.org/wiki/Tokyo"
        assert isinstance(chunk["chunk_index"], int)
        assert isinstance(chunk["content_text"], str) and chunk["content_text"]
        assert isinstance(chunk["content_html"], str) and chunk["content_html"]


def test_page_title_extracted_from_html_title_tag():
    parsed = parse_page(SAMPLE_HTML, "Fallback Title")
    chunks = chunk_page(parsed["title"], "https://example.com", parsed["elements"])
    assert all(c["page_title"] == "Tokyo Travel Guide" for c in chunks)


def test_page_title_falls_back_when_no_title_tag():
    html_no_title = "<html><body><h1>X</h1><p>Some content here.</p></body></html>"
    parsed = parse_page(html_no_title, "Fallback Title")
    chunks = chunk_page(parsed["title"], "https://example.com", parsed["elements"])
    assert all(c["page_title"] == "Fallback Title" for c in chunks)


def test_section_path_reflects_heading_hierarchy():
    parsed = parse_page(SAMPLE_HTML, "Fallback Title")
    chunks = chunk_page(parsed["title"], "https://example.com", parsed["elements"])

    section_paths = [c["section_path"] for c in chunks]
    # H2 "See" and H2 "Eat" should each start their own section, nested
    # under the H1 "Tokyo" — the exact breadcrumb format
    # (e.g. "Tokyo > See") is what flyio-ai-llm embeds for retrieval
    # signal (see that repo's Phase 3 pre_chunked work).
    assert any("See" in p for p in section_paths)
    assert any("Eat" in p for p in section_paths)


def test_chunk_index_is_sequential_and_zero_based():
    parsed = parse_page(SAMPLE_HTML, "Fallback Title")
    chunks = chunk_page(parsed["title"], "https://example.com", parsed["elements"])
    indices = [c["chunk_index"] for c in chunks]
    assert indices == list(range(len(chunks)))
    assert indices[0] == 0


def test_content_html_has_no_script_or_style_tags():
    """render_semantic_html() only emits h1-h6/p/ul/ol/li/table — confirms
    no raw/unsafe markup survives into what gets stored and potentially
    rendered downstream.
    """
    html_with_script = SAMPLE_HTML.replace(
        "</body>", "<script>alert('x')</script><style>.x{color:red}</style></body>"
    )
    parsed = parse_page(html_with_script, "Fallback Title")
    chunks = chunk_page(parsed["title"], "https://example.com", parsed["elements"])
    for chunk in chunks:
        assert "<script" not in chunk["content_html"]
        assert "<style" not in chunk["content_html"]


# A Wikipedia article's body has no H1 — the title is page chrome, and every
# real section is an H2. This is the shape most pages crawled in practice
# actually have, and it used to be the one the heading stack got wrong.
WIKIPEDIA_STYLE_HTML = """
<html>
<head><title>Dwarka - Wikipedia</title></head>
<body>
  <h2>Etymology</h2>
  <p>The name Dwarka is derived from the Sanskrit words dvara and ka.</p>
  <h2>History</h2>
  <p>Dwarka has been continuously inhabited for a very long period of time.</p>
  <h2>Geography and climate</h2>
  <p>Dwarka is located on the western shore of the Okhamandal peninsula.</p>
  <h2>External links</h2>
  <p>Official website of the Dwarka municipality and tourism board.</p>
</body>
</html>
"""


def test_sibling_sections_are_not_nested_under_the_first_one():
    """Every H2 on a page whose body starts at H2 is a top-level section.

    The heading stack used to truncate to `stack[: level - 1]`, which assumes
    an H2 always sits at index 1 below an H1. With no H1 the first H2 landed
    at index 0 and survived every later truncation, so the whole page came
    back as "Etymology > History", "Etymology > External links" and so on —
    every section a child of whichever one happened to come first.
    """
    parsed = parse_page(WIKIPEDIA_STYLE_HTML, "Dwarka - Wikipedia")
    chunks = chunk_page(parsed["title"], "https://en.wikipedia.org/wiki/Dwarka", parsed["elements"])

    paths = [c["section_path"] for c in chunks]

    assert all(" > " not in p for p in paths), (
        f"sibling H2 sections must not nest under each other, got: {paths}"
    )
    for expected in ("Etymology", "History", "Geography and climate", "External links"):
        assert expected in paths, f"missing section {expected!r} in {paths}"


def test_h1_page_still_nests_sections_under_the_h1():
    """The fix must not flatten pages that genuinely do have an H1."""
    parsed = parse_page(SAMPLE_HTML, "Fallback Title")
    chunks = chunk_page(parsed["title"], "https://example.com", parsed["elements"])

    paths = [c["section_path"] for c in chunks]
    assert "Tokyo > See" in paths
    assert "Tokyo > Eat" in paths


def test_returning_to_a_shallower_level_pops_deeper_headings():
    """H2 'B' following H3 'A1' is a sibling of 'A', not a descendant of it."""
    html = """
    <html><head><title>T</title></head><body>
      <h1>Top</h1><p>Intro paragraph for the page.</p>
      <h2>A</h2><p>Section A body text goes here.</p>
      <h3>A1</h3><p>Subsection A1 body text goes here.</p>
      <h2>B</h2><p>Section B body text goes here.</p>
    </body></html>
    """
    parsed = parse_page(html, "T")
    chunks = chunk_page(parsed["title"], "https://example.com", parsed["elements"])

    paths = [c["section_path"] for c in chunks]
    assert "Top > B" in paths, paths
    assert not any(p.startswith("Top > A > ") and p.endswith("B") for p in paths), paths
