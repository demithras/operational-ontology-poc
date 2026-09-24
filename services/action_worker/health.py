"""services/action_worker health/metrics HTTP endpoint — same stdlib
http.server-in-a-thread pattern as services/projection_builder/health.py
(and for the same reason: the Temporal worker itself runs its own asyncio
event loop, not this thread)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.ready = False
        self.workflows_started = 0
        self.workflows_completed = 0
        self.workflows_failed = 0
        self.last_error: str | None = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": "ok" if self.ready else "starting",
                "service": "action_worker",
                "workflows_started": self.workflows_started,
                "workflows_completed": self.workflows_completed,
                "workflows_failed": self.workflows_failed,
                "last_error": self.last_error,
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
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="action-worker-health")
    thread.start()
    return server
