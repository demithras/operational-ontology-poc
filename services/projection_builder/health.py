"""Projection-builder health/metrics HTTP endpoint. Same stdlib
http.server-in-a-thread pattern as services/ingestion/health.py (and for
the same reason: the poll loop is a tight synchronous sleep/build loop, not
an async framework)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.builds_completed = 0
        self.builds_failed = 0
        self.last_error: str | None = None
        self.ready = False
        self.last_build_ms: float | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": "ok" if self.ready else "starting",
                "builds_completed": self.builds_completed,
                "builds_failed": self.builds_failed,
                "last_error": self.last_error,
                "last_build_ms": self.last_build_ms,
            }

    def incr(self, field: str, by: int = 1) -> None:
        with self._lock:
            setattr(self, field, getattr(self, field) + by)

    def set_error(self, message: str | None) -> None:
        with self._lock:
            self.last_error = message

    def set_ready(self, ready: bool) -> None:
        with self._lock:
            self.ready = ready

    def set_last_build_ms(self, ms: float) -> None:
        with self._lock:
            self.last_build_ms = ms


def make_handler(state: HealthState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/health":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(state.snapshot()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            pass

    return Handler


def start_health_server(state: HealthState, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="projection-builder-health")
    thread.start()
    return server
