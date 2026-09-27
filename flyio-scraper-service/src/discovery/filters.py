"""
Candidate URL filtering, scoring and capping.

This is the part that separates "automated crawling" from "automated garbage
collection". A raw search result list for any Indian destination is mostly
aggregator spam, Pinterest boards and Quora threads; embedding those puts them
in the same vector space as Wikivoyage, where they compete for retrieval
against the content that actually answers the question.

Three gates, in order:
  1. reject  — not http(s), or on the denied-domain list
  2. score   — trusted domains rank above unknown ones
  3. cap     — total budget, and a per-domain cap so one site cannot take
               every slot
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

# Query parameters that identify a campaign or a session rather than a
# document. Two URLs differing only in these are the same page, so they are
# dropped before the canonical form is compared — otherwise the same article
# arriving from two queries gets crawled and embedded twice.
_TRACKING_PREFIXES = ("utm_", "ga_", "_hs", "mc_")
_TRACKING_PARAMS = frozenset(
    {
        "fbclid", "gclid", "dclid", "msclkid", "igshid", "mkt_tok",
        "ref", "referrer", "source", "src", "campaign", "spm",
    }
)

# Domains that reliably carry structured, factual destination content. Ranked
# in tiers rather than a flat allowlist so an unknown-but-plausible domain can
# still be surfaced for review instead of being silently dropped — the operator
# sees it in the candidate list and decides.
TRUSTED_DOMAINS: dict[str, int] = {
    # Tier 1 — encyclopaedic / official. Section-structured, licence-clean,
    # and what the chunker was built against.
    "wikivoyage.org": 100,
    "wikipedia.org": 90,
    "incredibleindia.gov.in": 90,
    "tourism.gov.in": 90,
    # Tier 2 — established travel publishers with real editorial pages.
    "lonelyplanet.com": 70,
    "holidify.com": 65,
    "tourmyindia.com": 65,
    "thrillophilia.com": 60,
    "traveltriangle.com": 60,
    "nativeplanet.com": 55,
    "tripadvisor.in": 50,
    "tripadvisor.com": 50,
}

# Any *.gov.in / *.nic.in state tourism board scores here without being listed
# individually — there are dozens and they are all first-party sources.
_GOV_SUFFIXES = (".gov.in", ".nic.in", ".gov")
_GOV_SCORE = 85

# Never crawl. Either the content is user-generated noise, the page is a
# booking funnel with no prose, or the site actively blocks crawlers and the
# attempt just burns a job slot.
DENIED_DOMAINS: frozenset[str] = frozenset(
    {
        "pinterest.com", "pinterest.co.uk", "in.pinterest.com",
        "quora.com", "reddit.com", "facebook.com", "instagram.com",
        "twitter.com", "x.com", "youtube.com", "tiktok.com",
        "linkedin.com", "medium.com",
        "booking.com", "agoda.com", "expedia.com", "makemytrip.com",
        "goibibo.com", "yatra.com", "cleartrip.com", "airbnb.com",
        "amazon.in", "amazon.com", "flipkart.com",
    }
)

# Non-document endpoints that occasionally rank. Crawling them yields no text.
_DENIED_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".zip", ".mp4", ".mp3", ".xml", ".json", ".csv",
)

DEFAULT_SCORE = 30
"""Score for a domain that is neither trusted nor denied — surfaced for
review, but ranked below anything known-good."""


@dataclass(frozen=True)
class Candidate:
    """One URL worth considering, with the reasoning that got it here."""

    url: str
    title: str
    domain: str
    score: int
    query: str
    """The expansion query that surfaced this URL — shown in the admin UI so
    an operator can see which topic a candidate covers."""
    trusted: bool


# Two-label public suffixes common in this corpus. Without them "mp.gov.in"
# would reduce to "gov.in" and every state tourism board would share one
# per-domain budget.
_TWO_LABEL_SUFFIXES = frozenset(
    {
        "gov.in", "nic.in", "ac.in", "co.in", "org.in", "net.in", "res.in",
        "co.uk", "gov.uk", "ac.uk", "org.uk",
        "com.au", "co.jp", "ne.jp", "or.jp", "com.br", "co.za", "co.nz",
    }
)


def registrable_domain(url: str) -> str:
    """Organizational domain of a URL, lowercased. Empty if unparseable.

    Reduces a host to the site that owns it — "en.wikivoyage.org" and
    "www.wikivoyage.org" both become "wikivoyage.org" — so the per-domain cap
    in `cap_candidates` counts one site once, rather than granting every
    subdomain its own budget. Handles the two-label suffixes above, so
    "mp.gov.in" stays whole instead of collapsing to "gov.in".

    Not a full public-suffix-list implementation; it does not need to be. A
    miss on an exotic TLD costs at most a slightly loose per-domain cap, and
    the trusted/denied tables are matched by suffix either way.
    """
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
    except ValueError:
        return ""
    if not host:
        return ""

    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _matches(domain: str, table) -> bool:
    """True if `domain` is an entry in `table` or a subdomain of one."""
    return any(domain == entry or domain.endswith("." + entry) for entry in table)


def canonicalize_url(url: str) -> str:
    """Reduce a URL to a stable identity for deduplication.

    Drops the fragment and tracking parameters, lowercases scheme and host,
    and removes a trailing slash from non-root paths. Meaningful query
    parameters are kept and sorted so ordering differences don't split one
    page into two candidates.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    # Drop a redundant default port so :443 and the bare host agree.
    if netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]
    elif netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]

    path = parsed.path
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
        and not k.lower().startswith(_TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(kept))

    return urlunparse((scheme, netloc, path, "", query, ""))


def is_crawlable(url: str) -> bool:
    """True if the URL is an absolute http(s) document URL.

    Mirrors the guard POST /scrape/urls applies, so a candidate that passes
    here cannot be rejected by the very endpoint it is destined for.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    return not parsed.path.lower().endswith(_DENIED_EXTENSIONS)


def score_domain(domain: str) -> tuple[int, bool]:
    """Return (score, trusted) for a domain.

    `trusted` drives auto-selection in the admin UI: trusted candidates come
    back pre-checked, unknown ones come back listed but unchecked.
    """
    for entry, value in TRUSTED_DOMAINS.items():
        if domain == entry or domain.endswith("." + entry):
            return value, True
    if domain.endswith(_GOV_SUFFIXES):
        return _GOV_SCORE, True
    return DEFAULT_SCORE, False


def is_denied(domain: str, extra_denied=()) -> bool:
    """True if the domain is on the built-in or deployment-specific denylist."""
    return _matches(domain, DENIED_DOMAINS) or (
        bool(extra_denied) and _matches(domain, extra_denied)
    )


def build_candidates(raw_results, extra_denied=()) -> list[Candidate]:
    """Filter and score raw search hits into Candidates, best first.

    Deduplicates on the canonical URL, keeping the first occurrence — results
    arrive in provider rank order, so the first sighting is the best-ranked
    one. Caps are applied separately by `cap_candidates`.
    """
    seen: set[str] = set()
    out: list[Candidate] = []

    for hit in raw_results:
        url = (hit.get("url") or "").strip()
        if not url or not is_crawlable(url):
            continue

        canonical = canonicalize_url(url)
        if canonical in seen:
            continue

        domain = registrable_domain(canonical)
        if not domain or is_denied(domain, extra_denied):
            continue

        seen.add(canonical)
        score, trusted = score_domain(domain)
        out.append(
            Candidate(
                url=canonical,
                title=(hit.get("title") or canonical).strip(),
                domain=domain,
                score=score,
                query=hit.get("query", ""),
                trusted=trusted,
            )
        )

    # Sort by score only, and rely on Python's stable sort to preserve provider
    # rank within a score band — a same-tier result that ranked higher in
    # search stays higher here.
    out.sort(key=lambda c: c.score, reverse=True)
    return out


def cap_candidates(
    candidates: list[Candidate], max_urls: int, max_per_domain: int
) -> list[Candidate]:
    """Trim to the crawl budget, at most `max_per_domain` from any one site.

    The per-domain cap is what keeps topic spread: Wikivoyage scores highest
    and matches all five expansion queries, so without it a 12-URL budget
    would be 12 Wikivoyage pages and the "where to stay" query would have
    contributed nothing.
    """
    per_domain: dict[str, int] = {}
    kept: list[Candidate] = []

    for cand in candidates:
        if len(kept) >= max_urls:
            break
        used = per_domain.get(cand.domain, 0)
        if used >= max_per_domain:
            continue
        per_domain[cand.domain] = used + 1
        kept.append(cand)

    return kept
