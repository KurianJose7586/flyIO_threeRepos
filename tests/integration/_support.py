"""Shared helpers for the integration suites: HTTP without the proxy, a
pass/fail tally, admin login, and direct SQL for arranging state the API
deliberately cannot set (e.g. back-dating a crawl to make it stale)."""
import json
import os
import subprocess
import urllib.error
import urllib.request

ADMIN = "http://127.0.0.1:3100"
SCRAPER = "http://127.0.0.1:8099"
STUB_LLM = "http://127.0.0.1:8101"
PG = ["psql", "-h", "127.0.0.1", "-p", os.environ.get("PGPORT", "5433"),
      "-U", "flyio", "-d", "flyio_admin_test", "-tAq", "-c"]

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}"
          + (f"\n          {detail}" if detail and not cond else ""))


def call(url, method="GET", body=None, token=None, timeout=300):
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
            return e.code, {"raw": raw.decode(errors="replace")[:400]}


def login():
    _, body = call(f"{ADMIN}/api/admin/login", "POST",
                   {"username": "admin", "password": "integration-test-admin-pw"})
    return body["token"]


def sql(statement):
    out = subprocess.run(PG + [statement], capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def reset():
    sql("TRUNCATE knowledge_base, history, job_events, jobs, prompt_history, "
        "request_events RESTART IDENTITY CASCADE;")
    call(f"{STUB_LLM}/__reset", "POST", {})


def summary():
    print("\n" + "=" * 62)
    print(f"  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("  FAILED: " + ", ".join(FAIL))
    print("=" * 62)
    return 1 if FAIL else 0
