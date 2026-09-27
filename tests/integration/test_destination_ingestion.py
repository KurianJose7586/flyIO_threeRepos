"""End-to-end integration test of the destination-driven ingestion path.

Real Postgres, real admin server, real scraper service, real crawl4ai
crawl against locally-served fixture pages, stubbed vector store. Only the
outbound search API and the embedding service are stubbed — everything
between them is production code.
"""
import json
import sys
import time
import urllib.request

ADMIN = "http://127.0.0.1:3100"
SCRAPER = "http://127.0.0.1:8099"
STUB_LLM = "http://127.0.0.1:8101"

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n          {detail}" if detail and not cond else ""))


def call(url, method="GET", body=None, token=None, timeout=180):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, data, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"{}")
        except Exception:
            return e.code, {"raw": raw.decode(errors="replace")[:300]}


def main():
    print("\n=== 0. Auth ===")
    st, body = call(f"{ADMIN}/api/admin/login", "POST",
                    {"username": "admin", "password": "integration-test-admin-pw"})
    token = body.get("token") or body.get("access_token") or (body.get("data") or {}).get("token")
    check("admin login returns a token", bool(token), f"status={st} body={str(body)[:200]}")
    if not token:
        return

    print("\n=== 1. POST /api/admin/discover — first run, nothing indexed ===")
    st, d1 = call(f"{ADMIN}/api/admin/discover", "POST", {"destination": "Jabalpur"}, token)
    check("returns 200", st == 200, f"status={st} body={str(d1)[:300]}")
    cands = d1.get("candidates", [])
    by_domain = {c["domain"]: c for c in cands}

    check("denied domain filtered out", not any("pinterest" in c["url"] for c in cands))
    check("duplicate collapsed (one wikivoyage candidate)",
          sum(1 for c in cands if c["domain"] == "wikivoyage.org") == 1)
    check("ranked by trust score", [c["score"] for c in cands] == sorted((c["score"] for c in cands), reverse=True))
    check("considered > kept (filtering happened)", d1.get("considered", 0) > len(cands),
          f"considered={d1.get('considered')} kept={len(cands)}")
    check("nothing marked already_indexed on a clean DB",
          all(c["already_indexed"] is False for c in cands))
    check("trusted candidates are recommended",
          all(c["recommended"] for c in cands if c["trusted"]))
    check("unknown domain listed but NOT recommended",
          by_domain.get("some-blog.example", {}).get("recommended") is False,
          str(by_domain.get("some-blog.example")))
    check("unknown domain reason explains why",
          "review" in (by_domain.get("some-blog.example", {}).get("reason", "").lower()))
    check("recommended_count matches", d1.get("recommended_count") == sum(1 for c in cands if c["recommended"]))

    print("\n=== 2. POST /api/admin/crawl/auto — full automatic ingest ===")
    st, a1 = call(f"{ADMIN}/api/admin/crawl/auto", "POST", {"destination": "Jabalpur"}, token)
    check("returns 200", st == 200, f"status={st} body={str(a1)[:400]}")
    check("a job was created", bool(a1.get("job_id")), str(a1)[:200])
    crawled = a1.get("urls", [])
    check("only trusted URLs auto-crawled (no unknown domain)",
          all("some-blog.example" not in u for u in crawled), str(crawled))
    check("crawled more than one domain", len({u.split("/")[2] for u in crawled}) > 1, str(crawled))
    check("crawl succeeded", a1.get("status") == "success", f"status={a1.get('status')} error={a1.get('error')}")
    check("every crawled URL succeeded", a1.get("failed") == 0, f"failed={a1.get('failed')} of {a1.get('total')}")

    print("\n=== 3. Chunks actually landed in knowledge_base ===")
    st, kb = call(f"{ADMIN}/api/admin/knowledge-base?limit=50", "GET", None, token)
    rows = kb.get("entries") or []
    kb_urls = {r.get("source_url") for r in rows} if rows else set()
    check("knowledge_base has rows for the crawled URLs",
          bool(kb_urls & set(crawled)), f"kb={list(kb_urls)[:4]} crawled={crawled}")

    print("\n=== 4. Vector store received the chunks ===")
    st, calls = call(f"{STUB_LLM}/__calls")
    store_calls = calls.get("calls", [])
    stored_urls = {u for c in store_calls for u in c["source_urls"]}
    check("store API was called", len(store_calls) > 0, f"calls={len(store_calls)}")
    check("stored chunks cover the crawled URLs", bool(stored_urls & set(crawled)),
          f"stored={list(stored_urls)[:4]}")
    check("every stored chunk carries a section_path",
          all(c["has_section_path"] for c in store_calls))

    print("\n=== 5. Dedup — re-running the SAME destination must not re-ingest ===")
    st, d2 = call(f"{ADMIN}/api/admin/discover", "POST", {"destination": "Jabalpur"}, token)
    c2 = d2.get("candidates", [])
    indexed = [c for c in c2 if c["already_indexed"]]
    check("previously crawled URLs now marked already_indexed", len(indexed) > 0,
          f"{[(c['domain'], c['already_indexed']) for c in c2]}")
    check("already-indexed candidates carry a chunk count",
          all(c["indexed_chunks"] > 0 for c in indexed),
          str([(c["domain"], c["indexed_chunks"]) for c in indexed]))
    check("already-indexed candidates are no longer recommended",
          all(c["recommended"] is False for c in indexed))
    check("already-indexed reason says so",
          all("already indexed" in c["reason"].lower() for c in indexed))

    calls_before = len(store_calls)
    st, a2 = call(f"{ADMIN}/api/admin/crawl/auto", "POST", {"destination": "Jabalpur"}, token)
    check("second auto-crawl is a no-op", a2.get("status") == "skipped",
          f"status={a2.get('status')} job_id={a2.get('job_id')}")
    check("second auto-crawl creates no job", a2.get("job_id") in (None, ""), str(a2.get("job_id")))
    check("second auto-crawl explains why", "already indexed" in (a2.get("detail", "").lower()),
          a2.get("detail", ""))
    st, calls2 = call(f"{STUB_LLM}/__calls")
    check("no new vector-store writes on the no-op",
          len(calls2.get("calls", [])) == calls_before,
          f"before={calls_before} after={len(calls2.get('calls', []))}")

    print("\n=== 6. Explicit selection is crawled exactly as approved ===")
    # No second search: results drift between preview and click, and an
    # approved page must not silently drop out. See test_review_regressions.
    approved = ["http://en.wikivoyage.org/wiki/Gorakhpur"]
    st, a3 = call(f"{ADMIN}/api/admin/crawl/auto", "POST",
                  {"destination": "Gorakhpur", "urls": approved}, token)
    check("explicit selection crawls", a3.get("status") == "success",
          f"status={a3.get('status')} error={a3.get('error')}")
    check("exactly the approved URLs were submitted", a3.get("urls") == approved, str(a3.get("urls")))

    print("\n=== 7. Error handling ===")
    st, _ = call(f"{ADMIN}/api/admin/discover", "POST", {"destination": "Jabalpur"})
    check("discover requires admin auth (401)", st == 401, f"status={st}")
    st, e2 = call(f"{ADMIN}/api/admin/discover", "POST", {}, token)
    check("missing destination -> 400", st == 400, f"status={st}")
    st, e3 = call(f"{ADMIN}/api/admin/discover", "POST", {"destination": "x"}, token)
    check("upstream 422 kept as a client error, not 502", st == 422, f"status={st} body={str(e3)[:200]}")
    check("422 detail is a readable sentence, not a pydantic dump",
          isinstance(e3.get("detail"), str) and "destination" in e3.get("detail", ""),
          repr(e3.get("detail"))[:200])

    print("\n" + "=" * 62)
    print(f"  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
