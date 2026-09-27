"""Tests for PromptBuilder component."""

from app.schemas.search import SearchResultItem
from app.services.prompt_builder import PromptBuilder


def test_prompt_builder_format_context_basic():
    """Verify format_context renders search items cleanly."""
    builder = PromptBuilder(max_context_results=5)
    results = [
        SearchResultItem(
            id="point-1",
            score=0.95,
            payload={"title": "Eiffel Tower Guide", "category": "sightseeing"},
            text="Eiffel tower ticket info and hours.",
        ),
        SearchResultItem(
            id="point-2",
            score=0.85,
            payload={"title": "Louvre Museum Guide"},
            text="Louvre opening times and Mona Lisa location.",
        ),
    ]

    context_str = builder.format_context(results)
    assert "[Context Item 1]" in context_str
    assert "Eiffel Tower Guide" in context_str
    assert "Relevance Score: 0.95" in context_str
    assert "[Context Item 2]" in context_str
    assert "Louvre Museum Guide" in context_str
    assert "Note: Context truncated" not in context_str


def test_prompt_builder_format_context_truncation():
    """Verify format_context caps results to max_results and appends truncation note."""
    builder = PromptBuilder(max_context_results=2)
    results = [
        SearchResultItem(id=f"doc-{i}", score=0.90 - i * 0.05, payload={}, text=f"Text snippet {i}")
        for i in range(5)
    ]

    context_str = builder.format_context(results)
    assert "[Context Item 1]" in context_str
    assert "[Context Item 2]" in context_str
    assert "[Context Item 3]" not in context_str
    assert "[Note: Context truncated to the 2 most relevant item(s) out of 5 total matches from vector database.]" in context_str


def test_prompt_builder_format_context_empty():
    """Verify empty search results return fallback text."""
    builder = PromptBuilder()
    assert builder.format_context([]) == "No background context available."


def test_prompt_builder_prompts():
    """Verify system, user, and retry prompts contain expected schema and corrective text."""
    builder = PromptBuilder()
    sys_prompt = builder.build_system_prompt()
    assert "FlyIO AI Travel Planning Engine" in sys_prompt
    assert "destinations" in sys_prompt
    assert "daily_schedule" in sys_prompt

    retry_prompt = builder.build_retry_system_prompt()
    assert "Your previous response was not valid JSON" in retry_prompt

    user_prompt = builder.build_user_prompt("Plan a 3-day Paris trip", "Context block")
    assert "User Travel Request:\nPlan a 3-day Paris trip" in user_prompt
    assert "Context block" in user_prompt


def test_llm_service_reads_configured_max_context_results(test_settings):
    """Verify LLMService passes settings.PROMPT_CONTEXT_MAX_RESULTS to PromptBuilder."""
    from app.services.llm.service import LLMService
    test_settings.PROMPT_CONTEXT_MAX_RESULTS = 8
    service = LLMService(settings=test_settings)
    assert service.prompt_builder.max_context_results == 8



# --- Context size budget (PROMPT_CONTEXT_MAX_CHARS) ---
#
# A result-count cap alone is not a bound on prompt size: each retrieved chunk
# can be arbitrarily long. Measured against real scraped Wikivoyage content,
# 5 results produced ~23k chars / ~14.2k tokens and the provider rejected the
# request outright ("Limit 8000, Requested 14231").

def test_format_context_stops_at_char_budget():
    """Oversized items must be dropped whole once the budget is reached, even
    when the result-count cap would have allowed them."""
    big = "x" * 5000
    results = [
        SearchResultItem(id=f"doc-{i}", score=0.9, payload={}, text=big)
        for i in range(5)
    ]
    builder = PromptBuilder(max_context_results=5, max_context_chars=12000)

    context_str = builder.format_context(results)

    assert len(context_str) < 15000, "context block ignored the character budget"
    # 5 x ~5000 chars would be ~25k; the budget must have cut it well short.
    assert "[Context Item 1]" in context_str
    assert "[Context Item 5]" not in context_str
    assert "truncated" in context_str


def test_format_context_always_keeps_at_least_one_item():
    """A single item larger than the whole budget must still be included —
    returning an empty context block would strip the model of all grounding
    and silently turn a RAG answer into a from-memory one."""
    huge = "y" * 50000
    results = [SearchResultItem(id="doc-0", score=0.9, payload={}, text=huge)]
    builder = PromptBuilder(max_context_results=5, max_context_chars=1000)

    context_str = builder.format_context(results)
    assert "[Context Item 1]" in context_str
    assert huge in context_str


def test_format_context_omits_bulk_payload_fields():
    """text/content/content_html must not be echoed inside 'Payload Details'.

    text is already emitted as 'Content:', and content_html is the HTML twin of
    that same text carried by scraper-sourced points — inlining both made every
    context item ~3.4x larger than the content it actually conveyed (measured
    on real scraped chunks), which is what blew the provider's token limit.
    """
    results = [
        SearchResultItem(
            id="doc-0", score=0.9,
            payload={
                "text": "THE_CHUNK_TEXT",
                "content_html": "<p>THE_HTML_TWIN</p>",
                "source_url": "https://example.com/page",
                "section_path": "Kyoto > See",
            },
            text="THE_CHUNK_TEXT",
        )
    ]
    context_str = PromptBuilder().format_context(results)

    # Useful metadata survives.
    assert "https://example.com/page" in context_str
    assert "Kyoto > See" in context_str
    # The HTML twin is gone entirely.
    assert "THE_HTML_TWIN" not in context_str
    # The chunk text appears exactly once (as Content:), not duplicated in the payload dump.
    assert context_str.count("THE_CHUNK_TEXT") == 1


def test_llm_service_reads_configured_max_context_chars(test_settings):
    """Verify LLMService passes settings.PROMPT_CONTEXT_MAX_CHARS to PromptBuilder."""
    from app.services.llm.service import LLMService
    test_settings.PROMPT_CONTEXT_MAX_CHARS = 4321
    service = LLMService(settings=test_settings)
    assert service.prompt_builder.max_context_chars == 4321
