"""
Two jobs:
  1. render_semantic_html(): turn parsed elements back into clean,
     minimal, semantic HTML (no styles/classes/scripts) for previewing
     and for storing alongside each chunk's plain text.
  2. chunk_page(): split a parsed page into embedding-ready chunks,
     using H1/H2 headings as the section boundary (CHUNK_HEADING_LEVEL
     in config.py). H3-H6 stay inline as sub-heading text within the
     current section rather than starting a new chunk — travel sites
     use H2 for their real sections ("Best Time to Visit", "How to
     Reach", "Things to Do"), so that's the natural chunk boundary.
"""
from html import escape
import re
import hashlib
from config import MAX_CHUNK_CHARS, CHUNK_OVERLAP_CHARS, CHUNK_HEADING_LEVEL


def content_fingerprint(text: str) -> str:
    """
    Normalized hash of a chunk's text, used to catch identical/near-identical
    content that shows up on different URLs or different sites (travel
    sites frequently copy each other's "best time to visit" style blurbs).
    Case/whitespace-insensitive so trivial formatting differences still match.
    """
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _esc(text: str) -> str:
    """Escape only what's unsafe in HTML text content (< > &). Leaving
    quotes/apostrophes un-escaped keeps content_html human/AI-readable
    (no more '&#x27;' where a plain apostrophe belongs) — safe here since
    this text never lands inside an HTML attribute."""
    return escape(text, quote=False)


def render_semantic_html(elements: list) -> str:
    parts = []
    for el in elements:
        if el["type"] == "heading":
            parts.append(f"<h{el['level']}>{_esc(el['text'])}</h{el['level']}>")
        elif el["type"] == "paragraph":
            parts.append(f"<p>{_esc(el['text'])}</p>")
        elif el["type"] == "list":
            tag = "ol" if el["ordered"] else "ul"
            items = "".join(f"<li>{_esc(i)}</li>" for i in el["items"])
            parts.append(f"<{tag}>{items}</{tag}>")
        elif el["type"] == "table":
            rows_html = "".join(
                "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in row) + "</tr>"
                for row in el["rows"]
            )
            parts.append(f"<table>{rows_html}</table>")
    return "\n".join(parts)


def _element_to_text(el: dict) -> str:
    if el["type"] == "heading":
        return el["text"]
    if el["type"] == "paragraph":
        return el["text"]
    if el["type"] == "list":
        return "\n".join(f"- {i}" for i in el["items"])
    if el["type"] == "table":
        return "\n".join(" | ".join(row) for row in el["rows"])
    return ""


def _section_path(stack: list) -> str:
    """Render the heading stack as breadcrumbs. `stack` holds (level, text)
    pairs — see the heading handling in chunk_page for why the level travels
    with the text."""
    return " > ".join(text for _level, text in stack) if stack else ""


def chunk_page(page_title: str, source_url: str, elements: list) -> list:
    """
    Splits elements into chunks along H1/H2 boundaries. Within a
    section, paragraphs/lists/H3-H6 accumulate until MAX_CHUNK_CHARS,
    then split with overlap. Tables are never split mid-row-set.
    Returns a list of chunk dicts ready for JSON export / embedding.
    """
    chunks = []
    # (level, text) pairs for the headings enclosing the current chunk.
    # The level travels with the text because the path has to be built from
    # the levels actually present on the page, not from their absolute
    # numbers — see the heading branch below.
    heading_stack: list = []
    current_text: list = []
    current_html_elements: list = []
    current_len = 0
    chunk_index = 0

    def flush():
        nonlocal current_text, current_html_elements, current_len, chunk_index
        if not current_text or not current_html_elements:
            # Nothing here but leftover overlap carried from the last
            # flush (section/page ended right after a boundary) — not a
            # real chunk. Drop it instead of emitting a ghost chunk.
            return
        text_blob = "\n\n".join(current_text)
        chunks.append({
            "source_url": source_url,
            "page_title": page_title,
            "section_path": _section_path(heading_stack),
            "chunk_index": chunk_index,
            "content_text": text_blob,
            "content_html": render_semantic_html(current_html_elements),
        })
        chunk_index += 1

        # Overlap is carried forward as whole ELEMENTS (never a raw text
        # slice) so content_text and content_html for the next chunk
        # always describe exactly the same content — no divergence
        # between the two fields. Never carries a heading across (that
        # would duplicate a section title into the body of the next
        # chunk), and skips overlap entirely if the single trailing
        # element already exceeds the overlap budget on its own (avoids
        # duplicating one giant paragraph into every following chunk).
        overlap_elements: list = []
        overlap_len = 0
        for el in reversed(current_html_elements):
            if el["type"] == "heading":
                break
            el_len = len(_element_to_text(el))
            if overlap_elements and overlap_len + el_len > CHUNK_OVERLAP_CHARS:
                break
            overlap_elements.insert(0, el)
            overlap_len += el_len
            if overlap_len >= CHUNK_OVERLAP_CHARS:
                break
        if overlap_elements and overlap_len > CHUNK_OVERLAP_CHARS * 2:
            overlap_elements, overlap_len = [], 0  # single oversized element — skip overlap

        current_text = [_element_to_text(el) for el in overlap_elements]
        current_html_elements = list(overlap_elements)
        current_len = overlap_len

    for el in elements:
        if el["type"] == "heading" and el["level"] <= CHUNK_HEADING_LEVEL:
            flush()
            level = el["level"]
            # Pop every heading at this level or deeper, then push. Nesting is
            # relative to the levels the page actually uses.
            #
            # This used to truncate to `heading_stack[: level - 1]`, which
            # assumes an H2 always sits at index 1 with an H1 above it. On a
            # page whose body has no H1 — Wikipedia articles, where the title
            # is chrome and every section is an H2 — the first H2 landed at
            # index 0, and each later H2 truncated to [:1], keeping it, then
            # appended. Every section on the page came out as a child of
            # whatever the first one happened to be: "Etymology > History",
            # "Etymology > References", "Etymology > External links". That
            # path is embedded alongside the chunk text and is part of the
            # deterministic point ID, so it degraded retrieval and tied every
            # ID on the page to its first heading.
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, el["text"]))
            current_html_elements.append(el)
            current_text.append(el["text"])
            current_len += len(el["text"])
            continue

        el_text = _element_to_text(el)
        el_len = len(el_text)

        if el["type"] == "table" and current_len + el_len > MAX_CHUNK_CHARS and current_text:
            flush()

        if current_len + el_len > MAX_CHUNK_CHARS and current_text:
            flush()

        current_text.append(el_text)
        current_html_elements.append(el)
        current_len += el_len

    flush()
    return chunks
