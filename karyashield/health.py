"""Tiny read-only status server for the worker (stdlib only). Never exposes secrets or snippets."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_lock = threading.Lock()
STATE: dict = {
    "service": "karyashield-worker",
    "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "host": None,
    "repo": None,
    "cycles": 0,
    "runs": 0,
    "last_sha": None,
    "last_run": None,  # summary counts only
    "total_issues_created": 0,
    "last_error_type": None,
}


def update(**kw) -> None:
    with _lock:
        STATE.update(kw)


def snapshot() -> dict:
    with _lock:
        return dict(STATE)


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/healthz":
            body, ctype = b"ok\n", "text/plain"
        elif self.path in ("/", "/status"):
            body, ctype = (json.dumps(snapshot(), indent=2) + "\n").encode(), "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep worker logs clean
        pass


def serve(port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
