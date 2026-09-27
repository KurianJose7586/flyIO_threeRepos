"""Serves the fixture pages at the paths the discovery mock points to."""
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

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
            name = self.path.rstrip("/").split("/")[-1] or "index"
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
