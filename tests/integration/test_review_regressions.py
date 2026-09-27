"""Regression tests for the four defects found in code review.

Each section reproduces one finding against the live stack. Run on a
clean database (the suite resets it itself).
"""
import sys

from _support import ADMIN, STUB_LLM, call, check, login, reset, sql, summary

WV_JAB = "http://en.wikivoyage.org/wiki/Jabalpur"
HOL_JAB = "http://www.holidify.com/wiki/Jabalpur"
# How a human might have pasted it from a newsletter. The crawler's own
# _normalize_url strips fragments and trailing slashes but keeps the query,
# so this is stored verbatim — while discovery canonicalises the tracking
# parameter away. (A bare trailing slash does not diverge: both sides strip it.)
HOL_JAB_VARIANT = HOL_JAB + "?utm_source=newsletter"
WV_GOR = "http://en.wikivoyage.org/wiki/Gorakhpur"


def main():
    reset()
    token = login()

    print("\n=== #4  Stored URL variant must count as already indexed ===")
    # Arrange: the page was ingested earlier through the manual path, pasted
    # with a trailing slash. Discovery canonicalises that slash away.
    st, r = call(f"{ADMIN}/api/admin/crawl", "POST", {"urls": HOL_JAB_VARIANT}, token)
    check("manual crawl of the tracking-param variant succeeds", st == 200 and r.get("status") == "success",
          f"status={st} body={str(r)[:200]}")
    check("rows stored under the variant exactly as pasted",
          sql(f"SELECT COUNT(*) FROM knowledge_base WHERE source_url = '{HOL_JAB_VARIANT}'") != ["0"])

    st, d = call(f"{ADMIN}/api/admin/discover", "POST", {"destination": "Jabalpur"}, token)
    hol = next((c for c in d.get("candidates", []) if c["domain"] == "holidify.com"), {})
    check("canonical candidate recognised as already indexed", hol.get("already_indexed") is True, str(hol)[:300])
    check("so it is not recommended for re-crawl", hol.get("recommended") is False, str(hol)[:300])
    check("candidate reports the URL it is stored under", hol.get("indexed_url") == HOL_JAB_VARIANT,
          f"indexed_url={hol.get('indexed_url')!r}")

    # Stale re-crawl must refresh the existing rows, not create a second copy.
    sql(f"UPDATE knowledge_base SET created_at = NOW() - INTERVAL '100 days' WHERE source_url = '{HOL_JAB_VARIANT}'")
    st, a = call(f"{ADMIN}/api/admin/crawl/auto", "POST", {"destination": "Jabalpur"}, token)
    check("stale page re-crawled under its stored URL", HOL_JAB_VARIANT in a.get("urls", []),
          f"urls={a.get('urls')}")
    variants = sql("SELECT DISTINCT source_url FROM knowledge_base WHERE source_url LIKE 'http://www.holidify.com/wiki/Jabalpur%'")
    check("exactly one copy of the page in knowledge_base", len(variants) == 1, f"variants={variants}")

    print("\n=== #1  Explicit selection must not depend on a fresh search ===")
    # Gorakhpur is not a Jabalpur search result. Search results drift between
    # the preview and the crawl click in production; this is that case.
    st, a = call(f"{ADMIN}/api/admin/crawl/auto", "POST",
                 {"destination": "Jabalpur", "urls": [WV_GOR]}, token)
    check("approved URL absent from a re-search is still crawled",
          a.get("status") == "success" and a.get("urls") == [WV_GOR],
          f"status={a.get('status')} urls={a.get('urls')} detail={a.get('detail')}")
    st, a = call(f"{ADMIN}/api/admin/crawl/auto", "POST",
                 {"destination": "Jabalpur", "urls": ["not-a-url"]}, token)
    check("invalid explicit URL rejected with 400", st == 400, f"status={st} body={str(a)[:200]}")
    st, a = call(f"{ADMIN}/api/admin/crawl/auto", "POST",
                 {"destination": "Jabalpur", "urls": "http://x.example/a"}, token)
    check("non-array urls rejected with 400", st == 400, f"status={st}")

    print("\n=== #3  data_required path must skip already-indexed sources ===")
    # Jabalpur's trusted sources are now all indexed and fresh.
    call(f"{STUB_LLM}/__reset", "POST", {})
    st, g = call(f"{ADMIN}/api/admin/llm/generate", "POST",
                 {"prompt": "Plan a trip", "destination": "Jabalpur"}, token)
    check("generate still succeeds", st == 200, f"status={st} body={str(g)[:200]}")
    _, calls = call(f"{STUB_LLM}/__calls")
    stored = {u for c in calls.get("calls", []) for u in c["source_urls"]}
    check("no already-indexed Jabalpur page re-embedded",
          not any("Jabalpur" in u for u in stored), f"stored={sorted(stored)}")
    rid = sql("SELECT request_id FROM prompt_history ORDER BY id DESC LIMIT 1")[0]
    ev = sql(f"SELECT metadata::text FROM request_events WHERE request_id = '{rid}' AND event_type = 'sources_discovered'")
    check("skip is recorded, naming what was skipped",
          bool(ev) and "skipped_already_indexed" in ev[0] and "Jabalpur" in ev[0], f"event={ev}")

    return summary()


if __name__ == "__main__":
    sys.exit(main())
