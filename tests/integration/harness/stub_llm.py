"""Stub of flyio-ai-llm, just enough for admin's ingestion path.

Records every /v1/api/store call so the integration test can assert what
actually reached the vector-store boundary, rather than only that the crawl
succeeded.
"""
import json, uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

STORE_CALLS = []
GENERATE_CALLS = []
# First /v1/api/generate answers data_required; the retry after ingestion
# answers data_found, mirroring the real service once Qdrant has content.


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/v1/health"):
            return self._json(200, {"status": "ok"})
        if self.path.startswith("/__calls"):
            return self._json(200, {"calls": STORE_CALLS, "generate_calls": GENERATE_CALLS})
        self._json(404, {"detail": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.startswith("/__reset"):
            # Lets a suite start from zero without restarting the process.
            STORE_CALLS.clear()
            GENERATE_CALLS.clear()
            return self._json(200, {"reset": True})
        if self.path.startswith("/v1/api/generate"):
            GENERATE_CALLS.append({"prompt": body.get("prompt", "")})
            first = len(GENERATE_CALLS) == 1
            if first:
                return self._json(200, {
                    "success": True,
                    "request_id": body.get("request_id") or "req_stub",
                    "status": "data_required",
                    "data_found": False,
                    "data_required": True,
                    "results": [],
                    "plan": None,
                    "message": "No relevant data in Qdrant.",
                    "metadata": {},
                })
            return self._json(200, {
                "success": True,
                "request_id": body.get("request_id") or "req_stub",
                "status": "data_found",
                "data_found": True,
                "data_required": False,
                "results": [{"id": "1", "score": 0.7, "payload": {}, "text": "x"}],
                "plan": {
                    "title": "3-Day Jabalpur Itinerary",
                    "summary": "Generated after ingestion.",
                    "destinations": [], "attractions": [], "hotels": [],
                    "daily_schedule": [],
                    "budget": {"currency": "INR", "accommodation_est": "0",
                               "activities_est": "0", "food_dining_est": "0",
                               "total_estimated": "0"},
                    "travel_tips": [],
                },
                "message": "Plan generated.",
                "metadata": {},
            })

        if self.path.startswith("/v1/api/store"):
            docs = body.get("documents") or []
            STORE_CALLS.append({
                "count": len(docs),
                "source_urls": sorted({d.get("source_url") for d in docs if d.get("source_url")}),
                "has_section_path": all(d.get("section_path") is not None for d in docs),
            })
            return self._json(200, {
                "success": True,
                "stored_count": len(docs),
                "document_ids": [str(uuid.uuid4()) for _ in docs],
                "message": f"stored {len(docs)}",
            })
        self._json(404, {"detail": "not found"})

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8101), Handler).serve_forever()
