"""Ingestion health/metrics HTTP endpoint (F38: "poison messages go to a
DLQ topic with a visible health metric"). Deliberately not FastAPI/uvicorn
— the consumer's main loop is a tight synchronous confluent_kafka.poll()
loop, so a plain stdlib http.server in a background daemon thread avoids
mixing that with an async framework's event loop.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthState:
    """Thread-safe counters the consumer loop updates and the HTTP handler
    reads. One instance shared between the server thread and the consumer
    loop thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.messages_consumed = 0
        self.messages_applied = 0
        self.messages_skipped_stale_or_duplicate = 0
        self.messages_quarantined_identity = 0
        self.poison_messages = 0
        self.last_error: str | None = None
        self.consumer_ready = False

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": "ok" if self.consumer_ready else "starting",
                "messages_consumed": self.messages_consumed,
                "messages_applied": self.messages_applied,
                "messages_skipped_stale_or_duplicate": self.messages_skipped_stale_or_duplicate,
                "messages_quarantined_identity": self.messages_quarantined_identity,
                "poison_messages": self.poison_messages,
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
            self.consumer_ready = ready


def make_handler(state: HealthState):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
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

        def log_message(self, fmt: str, *args) -> None:  # silence default stderr logging
            pass

    return Handler


def start_health_server(state: HealthState, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="ingestion-health")
    thread.start()
    return server
