"""services/reconciliation health/metrics HTTP endpoint — same stdlib
http.server-in-a-thread pattern as services/projection_builder/health.py."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.ready = False
        self.cycles_completed = 0
        self.decisions_watched = 0
        self.convergences = 0
        self.alerts_raised = 0
        self.last_error: str | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": "ok" if self.ready else "starting",
                "service": "reconciliation",
                "cycles_completed": self.cycles_completed,
                "decisions_watched": self.decisions_watched,
                "convergences": self.convergences,
                "alerts_raised": self.alerts_raised,
                "last_error": self.last_error,
            }

    def incr(self, field: str, by: int = 1) -> None:
        with self._lock:
            setattr(self, field, getattr(self, field) + by)

    def set(self, field: str, value) -> None:
        with self._lock:
            setattr(self, field, value)

    def set_error(self, message: str | None) -> None:
        with self._lock:
            self.last_error = message

    def set_ready(self, ready: bool) -> None:
        with self._lock:
            self.ready = ready


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
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="reconciliation-health")
    thread.start()
    return server
