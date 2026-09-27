"""Load, scale and failure behaviour of the live stack.

Unlike the other suites these mostly *measure*: they record where the
system's limits are and assert only what must hold at those limits (no
errors under concurrency, correct dedup at scale, no job stuck forever).
Numbers are printed so a run doubles as a capacity report.

Resets the database itself. Section 4 kills and restarts the scraper.
"""
import os
import statistics
import subprocess
import sys
import threading
import time

from _support import ADMIN, SCRAPER, call, check, login, reset, sql, summary

HERE = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(HERE, "harness", "up.sh")


def timed(fn):
    t = time.perf_counter()
    out = fn()
    return out, time.perf_counter() - t


def parallel(n, fn):
    results = [None] * n
    def run(i):
        results[i] = timed(fn)
    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads: t.start()
    for t in threads: t.join()
    return results


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def main():
    reset()
    token = login()

    print("\n=== 1. Concurrent discovery (40 parallel, through admin + Postgres) ===")
    res = parallel(40, lambda: call(f"{ADMIN}/api/admin/discover", "POST", {"destination": "Jabalpur"}, token))
    codes = [r[0][0] for r in res]
    lat = [r[1] for r in res]
    print(f"  latency  p50={pct(lat,50)*1000:.0f}ms  p95={pct(lat,95)*1000:.0f}ms  max={max(lat)*1000:.0f}ms")
    check("all 40 concurrent requests succeed", codes.count(200) == 40, f"codes={sorted(set(codes))}")
    check("every response identical (no cross-request bleed)",
          len({tuple(c["url"] for c in r[0][1]["candidates"]) for r in res}) == 1)

    print("\n=== 2. Crawl throughput (real headless Chromium) ===")
    (st, a), t_one = timed(lambda: call(f"{ADMIN}/api/admin/crawl/auto", "POST", {"destination": "Jabalpur"}, token))
    pages = len(a.get("urls", []))
    print(f"  {pages} pages crawled+chunked+stored in {t_one:.1f}s  ({t_one / max(pages,1):.1f}s/page)")
    check("sequential auto-crawl succeeds", a.get("status") == "success", str(a)[:200])

    # Two destinations at once. The scraper has one serial worker, so these
    # queue rather than run in parallel — both must still complete.
    res = parallel(2, lambda: None)  # warm threads
    dests = iter(["Gorakhpur", "Varanasi"])
    lock = threading.Lock()
    def crawl_next():
        with lock:
            d = next(dests)
        return call(f"{ADMIN}/api/admin/crawl/auto", "POST", {"destination": d}, token)
    res = parallel(2, crawl_next)
    wall = max(r[1] for r in res)
    statuses = [r[0][1].get("status") for r in res]
    print(f"  2 concurrent destinations finished in {wall:.1f}s  (statuses: {statuses})")
    # Varanasi has no fixture page: the server answers 404 for it. Neither
    # request may hang or take the other down.
    check("concurrent auto-crawls both return", all(r[0][0] in (200, 502) for r in res),
          f"codes={[r[0][0] for r in res]}")
    check("the destination with a real page still succeeds alongside a failing one",
          "success" in statuses, str(statuses))
    # A dead link is a normal search result. Its error page must not become
    # knowledge: it used to be stored and embedded as "Error code: 404".
    check("the 404 destination is reported failed, not success", "failed" in statuses, str(statuses))
    junk = sql("SELECT COUNT(*) FROM knowledge_base WHERE source_url LIKE '%Varanasi%'")[0]
    check("no error-page content stored for it", junk == "0", f"{junk} rows stored")

    print("\n=== 3. Dedup at knowledge-base scale ===")
    # 20,000 chunks across 5,000 other pages on the same host as a real
    # candidate. Matching is by canonical URL, fetched per host — this is
    # the case that strategy has to survive.
    sql("""INSERT INTO knowledge_base (source_url, chunk_data, extracted_content, created_at)
           SELECT 'http://en.wikivoyage.org/wiki/Filler_' || (g / 4),
                  jsonb_build_object('content_text', 'filler', 'chunk_index', g % 4),
                  'filler', NOW()
           FROM generate_series(1, 20000) g""")
    rows = int(sql("SELECT COUNT(*) FROM knowledge_base")[0])
    lat = []
    for _ in range(5):
        (st, d), t = timed(lambda: call(f"{ADMIN}/api/admin/discover", "POST", {"destination": "Jabalpur"}, token))
        lat.append(t)
    wv = next((c for c in d.get("candidates", []) if c["domain"] == "wikivoyage.org"), {})
    print(f"  {rows:,} KB rows · discover p50={statistics.median(lat)*1000:.0f}ms max={max(lat)*1000:.0f}ms")
    check("real page still recognised among 5,000 same-host pages", wv.get("already_indexed") is True, str(wv)[:200])
    check("discover stays under 2s at this scale", max(lat) < 2.0, f"max={max(lat):.2f}s")

    print("\n=== 4. Scraper crashes mid-job ===")
    # The scraper keeps jobs in memory. Kill it while a job is queued and
    # see whether admin notices, or waits on a job that no longer exists.
    sql("DELETE FROM knowledge_base WHERE source_url LIKE '%Gorakhpur%'")
    st, a = call(f"{ADMIN}/api/admin/crawl/auto?async=true", "POST",
                 {"destination": "Gorakhpur", "urls": ["http://en.wikivoyage.org/wiki/Gorakhpur"]}, token)
    job = a.get("job_id")
    subprocess.run(["pkill", "-f", "run_scraper_fix[t]ure"])
    time.sleep(2)
    subprocess.run([UP], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=os.environ.copy())
    scraper_up = call(f"{SCRAPER}/health")[0] == 200
    check("scraper restarts", scraper_up)

    t0, final = time.time(), None
    while time.time() - t0 < 180:
        st, s = call(f"{ADMIN}/api/admin/jobs/{job}/status", token=token)
        if s.get("status") in ("success", "failed"):
            final = s
            break
        time.sleep(3)
    took = time.time() - t0
    print(f"  job after crash: {final.get('status') if final else 'STILL PENDING'} after {took:.0f}s"
          + (f" — {final.get('error') or final.get('detail') or ''}"[:140] if final else ""))
    check("orphaned job reaches a terminal state (not stuck forever)", final is not None)
    check("orphaned job is reported as failed, not success",
          final is not None and final.get("status") == "failed", str(final)[:200])

    return summary()


if __name__ == "__main__":
    sys.exit(main())
