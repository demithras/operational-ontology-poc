"""Phase 10a item 5: minimal OpenTelemetry tracing.

Deliberately narrow scope, disclosed rather than hidden: only
services/decision_service is instrumented (its propose/approve/execute
endpoints — the hot path every governed decision goes through), not
action_worker/projection_builder/reconciliation. A trace/span is created
per request and stamped with the identifiers docs/experiment/briefs/
phase10a.md item 5 asks for — `decision_id`, `action_execution_id` (once
known), `actor_id` — via ordinary span attributes; `trace_id` is the span's
own OpenTelemetry-assigned identifier, read back via
`current_trace_id_hex()` so callers can log/return it for correlation.

F40 (docs/experiment/spec/09_failure_and_adversarial_matrix.md: "trace/log
unavailable -> business correctness survives"): every function here is a
no-op (never raises) when the SDK isn't installed, tracing was never
initialized, or the collector is unreachable. `init_tracing()` uses a
`BatchSpanProcessor` (export happens on a background thread, decoupled
from the request path — a stuck/unreachable collector adds no latency to
any real request) with a short OTLPSpanExporter `timeout` so a dead
collector's background export attempts fail fast rather than pile up.
`traced_span()` wraps `start_as_current_span` in try/except for the same
reason belt-and-suspenders: even a broken/misconfigured SDK must never
turn "record a trace" into "fail the business request".
"""

from __future__ import annotations

import contextlib
import os
from typing import Callable, Iterator, Optional

_ENABLED = False


def _noop_setter(_key: str, _value: object) -> None:
    return None


def init_tracing(service_name: str) -> bool:
    """Idempotent. Returns True if tracing was actually initialized (SDK
    present and no import/setup error), False otherwise — callers never
    need to check the return value (every other function here degrades to
    a no-op regardless), it's informational only (e.g. for a service's own
    /health response)."""
    global _ENABLED
    if _ENABLED:
        return True
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)
        # endpoint=None -> SDK reads OTEL_EXPORTER_OTLP_TRACES_ENDPOINT /
        # OTEL_EXPORTER_OTLP_ENDPOINT itself (unset in a bare `pytest`
        # host-side run, which is fine: BatchSpanProcessor's background
        # thread then just fails its export attempts silently, per F40).
        exporter = OTLPSpanExporter(timeout=2)
        provider.add_span_processor(BatchSpanProcessor(exporter, schedule_delay_millis=500))
        trace.set_tracer_provider(provider)
        _ENABLED = True
        return True
    except Exception:  # noqa: BLE001 - F40: tracing setup failure must never block startup
        return False


@contextlib.contextmanager
def traced_span(name: str, **attributes: object) -> Iterator[Callable[[str, object], None]]:
    """Best-effort span. Attribute values that are None are skipped (many
    callers won't yet know action_execution_id at propose() time). Yields a
    `set_attr(key, value)` callable so a caller can add attributes it only
    learns partway through the request (e.g. `decision_id` once propose()
    has actually run, `action_execution_id` once execute() derives it) —
    a no-op when tracing is disabled or the span itself failed to start.

    IMPORTANT (F40, and covered directly by tests/component/test_tracing.py
    ::test_traced_span_propagates_real_exceptions_from_its_body): only span
    SETUP/TEARDOWN failures are caught here. A real exception raised by the
    caller's OWN code inside the `with` block must propagate normally —
    tracing degrading gracefully must never also mean silently swallowing
    the business error the caller was trying to handle."""
    if not _ENABLED:
        yield _noop_setter
        return

    set_attr: Callable[[str, object], None] = _noop_setter
    _end_span: Callable[[], None] = lambda: None
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("services.decision_service")
        span_cm = tracer.start_as_current_span(name)
        span = span_cm.__enter__()
        _end_span = lambda: span_cm.__exit__(None, None, None)
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)

        def _set_attr(key: str, value: object) -> None:
            if value is not None:
                try:
                    span.set_attribute(key, value)
                except Exception:  # noqa: BLE001 - F40
                    pass

        set_attr = _set_attr
    except Exception:  # noqa: BLE001 - F40: span setup failure must never fail the request
        set_attr = _noop_setter
        _end_span = lambda: None

    try:
        yield set_attr
    finally:
        try:
            _end_span()
        except Exception:  # noqa: BLE001 - F40: span teardown failure must never fail the request
            pass


def current_trace_id_hex() -> Optional[str]:
    if not _ENABLED:
        return None
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx is None or ctx.trace_id == 0:
            return None
        return format(ctx.trace_id, "032x")
    except Exception:  # noqa: BLE001
        return None


def enabled() -> bool:
    return _ENABLED


def _reset_for_tests() -> None:
    """Test-only escape hatch (tests/component/test_tracing.py) — OTel's
    global TracerProvider can only be SET once per process by design,
    so `init_tracing()`'s idempotency guard is itself what this resets."""
    global _ENABLED
    _ENABLED = False
