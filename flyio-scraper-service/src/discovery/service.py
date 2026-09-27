"""
Discovery orchestration: destination in, ranked candidate URLs out.

Stateless by design, like the rest of this service. Deduplication against
what is *already* in the knowledge base happens in flyio-admin, which owns
the Postgres `knowledge_base` table and its `source_url` column; this service
has no database and should not grow one just to answer that question.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.config.settings import get_settings
from src.discovery.filters import Candidate, build_candidates, cap_candidates
from src.discovery.providers import SearchError, get_provider, search_all
from src.discovery.queries import InvalidDestinationError, build_queries


class DiscoveryError(RuntimeError):
    """Discovery could not produce a usable result."""


@dataclass
class DiscoveryResult:
    destination: str
    queries: list[str]
    candidates: list[Candidate]
    considered: int
    """How many raw hits came back before filtering — the denominator behind
    'kept 8 of 34', which is the number that tells an operator whether the
    filters are too tight or too loose."""
    errors: list[str]


async def discover(destination: str, max_urls: int | None = None) -> DiscoveryResult:
    """Expand a destination into ranked, filtered, capped candidate URLs.

    Raises DiscoveryError for a bad destination or an unusable provider —
    both are caller errors that no retry will fix.
    """
    settings = get_settings()

    try:
        queries = build_queries(destination)
    except InvalidDestinationError as exc:
        raise DiscoveryError(str(exc)) from exc

    try:
        provider = get_provider(settings.SEARCH_PROVIDER, settings.SEARCH_API_KEY)
    except SearchError as exc:
        raise DiscoveryError(str(exc)) from exc

    budget = max_urls if max_urls is not None else settings.DISCOVERY_MAX_URLS

    hits, errors = await search_all(
        provider, queries, settings.DISCOVERY_RESULTS_PER_QUERY
    )

    # Every query failing means the provider is down or the key is wrong.
    # Reporting that as "0 candidates found" would read as "nothing exists
    # for this destination" and send someone hunting the wrong problem.
    if not hits and errors:
        raise DiscoveryError(
            f"All {len(queries)} search queries failed. First error — {errors[0]}"
        )

    candidates = build_candidates(hits, extra_denied=settings.get_denied_domains())
    capped = cap_candidates(
        candidates, budget, settings.DISCOVERY_MAX_PER_DOMAIN
    )

    return DiscoveryResult(
        destination=destination.strip(),
        queries=queries,
        candidates=capped,
        considered=len(hits),
        errors=errors,
    )
