"""Crawl URLs live, without starting any service, and say what happened.

    python scripts/try_crawl.py https://en.wikivoyage.org/wiki/Delhi
    python scripts/try_crawl.py URL [URL ...]

Runs the same fetch, parse and chunk steps as a scraper job, and prints how
many chunks each URL produced - or, for wiki pages, why the MediaWiki API
fetch failed. Nothing is stored or sent to the admin or the vector DB.
"""
import argparse
import asyncio
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SERVICE_API_KEY", "unused-by-this-script")


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("urls", nargs="+")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="  [%(levelname)s] %(message)s")
    # httpx logs every request at INFO; keep the output to what matters.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    from src.config.settings import get_settings  # noqa: E402 — after env is set
    from src.crawler.wikimedia_fetch import fetch_wiki_page, wiki_article_title  # noqa: E402
    from src.crawler.wrapper import run_crawl_urls  # noqa: E402

    ua = get_settings().SEARCH_USER_AGENT
    for url in args.urls:
        if wiki_article_title(url):
            print(f"MediaWiki API check for {url}")
            started = time.monotonic()
            try:
                page = fetch_wiki_page(url, ua)
                print(f"  ok: {len(page['html']):,} characters of article HTML in {time.monotonic() - started:.1f}s")
            except Exception as exc:  # noqa: BLE001 — reporting is the point
                print(f"  FAILED after {time.monotonic() - started:.1f}s: {type(exc).__name__}: {exc}")
        else:
            print(f"{url} is not a wiki article; it is crawled with the headless browser.")

    print("\nFull crawl (as a scraper job runs it) ...")
    started = time.monotonic()
    try:
        chunks = asyncio.run(run_crawl_urls(args.urls))
    except Exception as exc:  # noqa: BLE001
        print(f"\nThe crawl raised {type(exc).__name__}: {exc}")
        return 1
    print(f"\nDone in {time.monotonic() - started:.1f}s")
    ok = True
    for url in args.urls:
        n = sum(1 for c in chunks if c.get("source_url") == url)
        ok = ok and n > 0
        print(f"  {n:4d} chunks  {url}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
