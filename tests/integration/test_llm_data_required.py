"""Exercises the data_required -> discovery -> ingest -> retry path in
routes/llm.ts, which nothing else covers."""
import json, sys, urllib.request, urllib.error

ADMIN = "http://127.0.0.1:3100"
STUB = "http://127.0.0.1:8101"
PASS, FAIL = [], []

def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"\n          {detail}" if detail and not cond else ""))

def call(url, method="GET", body=None, token=None, timeout=300):
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    if token: req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, data, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try: return e.code, json.loads(raw or b"{}")
        except Exception: return e.code, {"raw": raw.decode(errors="replace")[:400]}

_, b = call(f"{ADMIN}/api/admin/login", "POST", {"username":"admin","password":"integration-test-admin-pw"})
token = b["token"]

print("\n=== data_required -> discovery -> ingest -> retry ===")
st, r = call(f"{ADMIN}/api/admin/llm/generate", "POST",
             {"prompt": "Plan a 3-day trip", "destination": "Jabalpur"}, token)
check("generate returns 200", st == 200, f"status={st} body={str(r)[:400]}")
check("plan produced after ingestion", (r.get("status") or r.get("data",{}).get("status")) in ("completed","data_found") or bool(r.get("plan")),
      f"status={r.get('status')} keys={list(r.keys())}")

st, calls = call(f"{STUB}/__calls")
check("LLM was retried after ingestion", len(calls.get("generate_calls", [])) >= 2,
      f"generate_calls={len(calls.get('generate_calls', []))}")
stored = {u for c in calls.get("calls", []) for u in c["source_urls"]}
check("discovery-sourced URLs were ingested (not DEFAULT_SOURCE_URLS)",
      any("Jabalpur" in u for u in stored), f"stored={sorted(stored)}")
check("only trusted domains ingested on the unattended path",
      all("some-blog.example" not in u for u in stored), f"stored={sorted(stored)}")

print("\n=== provenance recorded ===")
# "Why was this page crawled?" has to stay answerable: an unattended crawl
# that leaves no trace of the destination that triggered it is unauditable.
st, prompts = call(f"{ADMIN}/api/admin/prompts?limit=5", "GET", None, token)
rows = prompts.get("prompts") or prompts.get("entries") or prompts.get("data") or []
check("prompt was recorded", len(rows) > 0, f"status={st} body={str(prompts)[:200]}")

if rows:
    rid = rows[0].get("request_id")
    st, detail = call(f"{ADMIN}/api/admin/prompts/{rid}", "GET", None, token)
    events = detail.get("events") or []
    types = [e.get("event_type") for e in events]
    check("data_required was logged", "data_required" in types, str(types))
    check("sources_discovered was logged", "sources_discovered" in types, str(types))
    discovered = next((e for e in events if e.get("event_type") == "sources_discovered"), {})
    meta = discovered.get("metadata") or {}
    if isinstance(meta, str):
        meta = json.loads(meta)
    check("discovery provenance names the destination",
          meta.get("destination") == "Jabalpur", str(meta)[:200])
    check("discovery provenance lists the URLs it chose",
          isinstance(meta.get("urls"), list) and len(meta["urls"]) > 0, str(meta)[:200])

print("\n" + "="*58)
print(f"  {len(PASS)} passed, {len(FAIL)} failed")
if FAIL: print("  FAILED: " + ", ".join(FAIL))
print("="*58)
sys.exit(1 if FAIL else 0)
