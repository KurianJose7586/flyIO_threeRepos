"""
Destination -> search query expansion.

One query ("Jabalpur") returns one page's worth of results, usually the same
top-ranked travel-listicle for every destination. The chunker organises a page
by section path ("Jaipur > See", "Jaipur > Get around"), so the knowledge base
is only as good as the topic spread of the pages fed into it: a single query
produces a vector store that answers "what to see" well and "how do I get
there" not at all.

Expanding into one query per topic mirrors the section structure the crawler
already produces, and costs nothing extra — search API pricing is per call and
DISCOVERY_MAX_URLS still caps how many pages actually get crawled.
"""
import re

# {destination} is substituted verbatim. Kept as a module constant rather than
# a setting because these track the chunker's section vocabulary, not a
# per-deployment preference.
QUERY_TEMPLATES: tuple[str, ...] = (
    "{destination} travel guide",
    "things to do in {destination}",
    "how to reach {destination} by train flight bus",
    "best time to visit {destination} weather",
    "where to stay in {destination}",
)

# Destination names reach here from an admin text box and end up in an outbound
# search URL. Anything that is not a letter, digit, space, hyphen or apostrophe
# is dropped rather than escaped — no legitimate place name needs it, and it
# keeps quotes and operators out of the provider's query parser.
_ALLOWED = re.compile(r"[^\w\s\-']", re.UNICODE)


class InvalidDestinationError(ValueError):
    """Raised when a destination is empty or sanitises away to nothing."""


def normalize_destination(destination: str) -> str:
    """Collapse whitespace and strip characters that don't belong in a query.

    Raises InvalidDestinationError if nothing usable is left, so a junk
    destination fails here rather than silently searching for "".
    """
    cleaned = _ALLOWED.sub(" ", destination or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise InvalidDestinationError(
            f"Destination {destination!r} contains no usable characters."
        )
    return cleaned


def build_queries(destination: str) -> list[str]:
    """Expand a destination into the per-topic search queries to run."""
    dest = normalize_destination(destination)
    return [tpl.format(destination=dest) for tpl in QUERY_TEMPLATES]


def extract_destination(query: str) -> str | None:
    """Recover the destination from a query built by `build_queries`.

    The reverse of the templates above. Used by the offline MockProvider,
    which only receives a query but needs the destination to synthesise
    believable URLs. Returns None if the query doesn't match any template.
    """
    for tpl in QUERY_TEMPLATES:
        prefix, _, suffix = tpl.partition("{destination}")
        if not query.startswith(prefix) or not query.endswith(suffix):
            continue
        middle = query[len(prefix): len(query) - len(suffix) if suffix else None]
        if middle.strip():
            return middle.strip()
    return None
