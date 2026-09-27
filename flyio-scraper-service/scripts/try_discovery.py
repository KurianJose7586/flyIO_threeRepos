"""Try destination discovery live, without starting any service.

    python scripts/try_discovery.py Jabalpur
    python scripts/try_discovery.py Jabalpur --provider wikimedia,duckduckgo

Reads SEARCH_PROVIDER etc. from .env like the service does (--provider
overrides it), runs the same search, filtering and ranking as
POST /scrape/discover, and prints what would be offered for crawling.
Nothing is crawled or stored.
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SERVICE_API_KEY", "unused-by-this-script")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("destination")
    parser.add_argument("--provider", help="override SEARCH_PROVIDER, e.g. wikimedia,duckduckgo")
    parser.add_argument("--max-urls", type=int, default=None)
    args = parser.parse_args()

    if args.provider:
        os.environ["SEARCH_PROVIDER"] = args.provider

    from src.config.settings import get_settings  # noqa: E402 — after env is set
    from src.discovery import DiscoveryError, discover  # noqa: E402

    print(f"Searching for {args.destination!r} with {get_settings().SEARCH_PROVIDER} …\n")
    try:
        result = asyncio.run(discover(args.destination, args.max_urls))
    except DiscoveryError as exc:
        print(f"FAILED: {exc}")
        return 1

    print(f"provider: {result.provider}   raw hits: {result.considered}   kept: {len(result.candidates)}\n")
    for c in result.candidates:
        mark = "auto" if c.trusted else "review"
        print(f"  [{mark:>6}] {c.score:>3}  {c.domain:<24} {c.url}")
    if result.errors:
        print(f"\n{len(result.errors)} search error(s) — coverage may be thin:")
        for e in result.errors[:5]:
            print(f"  - {e}")
    return 0 if result.candidates else 2


if __name__ == "__main__":
    sys.exit(main())
