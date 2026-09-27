"""Serves the fixture pages at the paths the discovery mock points to."""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fixtures", "wiki")
HITS = []

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        HITS.append(self.path)
        if self.path == "/robots.txt":
            body = b"User-agent: *\nAllow: /\n"
            ctype = "text/plain"
        elif self.path == "/__hits":
            body = ("\n".join(HITS)).encode()
            ctype = "text/plain"
        else:
            # Match on the path alone, like a real site: a tracking parameter
            # does not change which page is served. (Looking the query up as
            # part of the file name 404'd — and the crawler used to ingest
            # that 404 page as content, so a test passed on it.)
            name = urlparse(self.path).path.rstrip("/").split("/")[-1] or "index"
            # A host-specific page wins (fixtures/<host>/<name>.html) so two
            # sites for one destination are genuinely different pages; the
            # shared fixtures/wiki/ copy is the fallback.
            host = (self.headers.get("Host") or "").split(":")[0].lower()
            path = os.path.join(os.path.dirname(ROOT), host, f"{name}.html")
            if not os.path.isfile(path):
                path = os.path.join(ROOT, f"{name}.html")
            if not os.path.isfile(path):
                self.send_error(404, "no fixture")
                return
            with open(path, "rb") as f:
                body = f.read()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 80), H).serve_forever()
