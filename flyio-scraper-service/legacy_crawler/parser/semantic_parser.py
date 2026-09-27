"""
Semantic HTML -> structured node extractor.

This is the core of the "AI-friendly structured data" redesign: instead
of manually categorized fields like {"best_time": "...", "food": "..."},
every page becomes an ordered list of the elements exactly as they
appear in the document:

    {"type": "heading",   "level": 1-6, "text": str}
    {"type": "paragraph", "text": str}
    {"type": "list",      "ordered": bool, "items": [str, ...]}
    {"type": "table",     "rows": [[str, ...], ...]}

Order is preserved so downstream chunking can reconstruct section
hierarchy (H1 > H2 > paragraphs/lists/tables under it) purely from
element order + heading level — no site-specific knowledge required.
"""
import re
from bs4 import BeautifulSoup

STRIP_TAGS = [
    "script", "style", "noscript", "nav", "footer", "header", "form",
    "iframe", "aside", "button", "svg", "input", "select", "textarea",
]

STRIP_SELECTORS = [
    ".advertisement", ".ads", ".cookie-banner", ".newsletter-signup",
    ".social-share", ".breadcrumbs", "#mw-navigation", "#footer",
    ".navbox", ".vector-header", ".printfooter", ".catlinks",
]


def _strip_boilerplate(soup: BeautifulSoup) -> BeautifulSoup:
    for tag_name in STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    for selector in STRIP_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()
    for tag in soup.find_all(True):
        for attr in ("style", "class", "id", "onclick", "onload"):
            if tag.has_attr(attr):
                del tag[attr]
    return soup


def _clean_text_spacing(text: str) -> str:
    """
    get_text(" ", strip=True) inserts a literal space every time it joins
    text around an inline tag (e.g. <a>Konkani</a>:  ->  "Konkani :").
    This collapses those spurious spaces before punctuation/possessives
    so link-heavy paragraphs (very common on Wikivoyage etc.) read
    naturally: "Konkani :" -> "Konkani:", "India 's" -> "India's".
    """
    text = re.sub(r"\s+([:;,.!?)\]])", r"\1", text)      # space before punctuation
    text = re.sub(r"([(\[])\s+", r"\1", text)             # space after ( or [
    text = re.sub(r"\s+'s\b", "'s", text)                  # "India 's" -> "India's"
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clean_title(raw: str) -> str:
    cleaned = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = _clean_text_spacing(cleaned)
    return cleaned


def _extract_table(table_tag) -> dict:
    rows = []
    for tr in table_tag.find_all("tr"):
        cells = [_clean_text_spacing(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    return {"rows": rows}


def _extract_list(list_tag, ordered: bool) -> dict:
    items = [_clean_text_spacing(li.get_text(" ", strip=True)) for li in list_tag.find_all("li", recursive=False)]
    return {"ordered": ordered, "items": items}


def parse_page(raw_html: str, fallback_title: str = "") -> dict:
    """
    Returns:
    {
      "title": str,          <- clean plain text, zero HTML tags
      "elements": [ ... ]    <- in document order, see module docstring
    }
    """
    soup = BeautifulSoup(raw_html, "lxml")

    title_tag = soup.find("title")
    if title_tag:
        title = _clean_title(title_tag.decode_contents())
    elif fallback_title:
        title = _clean_title(fallback_title)
    else:
        title = ""

    soup = _strip_boilerplate(soup)
    body = soup.body if soup.body else soup

    elements = []
    seen_list_tags = set()

    for tag in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "table", "ul", "ol"]):
        if tag.name in ("ul", "ol"):
            if id(tag) in seen_list_tags:
                continue
            seen_list_tags.add(id(tag))
            data = _extract_list(tag, ordered=(tag.name == "ol"))
            if data["items"]:
                elements.append({"type": "list", **data})

        elif tag.name == "table":
            data = _extract_table(tag)
            if data["rows"]:
                elements.append({"type": "table", **data})

        elif tag.name == "p":
            text = _clean_text_spacing(tag.get_text(" ", strip=True))
            if text:
                elements.append({"type": "paragraph", "text": text})

        else:  # h1-h6
            text = _clean_text_spacing(tag.get_text(" ", strip=True))
            if text:
                elements.append({"type": "heading", "level": int(tag.name[1]), "text": text})

    return {"title": title, "elements": elements}
