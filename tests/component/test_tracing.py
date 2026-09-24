"""Phase 10a item 5: services/common/tracing.py unit coverage — no docker/
collector required. F40 (docs/experiment/spec/09_failure_and_adversarial_matrix.md:
"trace/log unavailable -> business correctness survives") at the unit
level: every function here must be a safe no-op before `init_tracing()` is
ever called, and `traced_span`'s body must always run regardless."""

from __future__ import annotations

from services.common import tracing


def test_traced_span_runs_body_when_tracing_never_initialized():
    tracing._reset_for_tests()
    ran = []
    with tracing.traced_span("unit.test", decision_id="D-1") as set_attr:
        ran.append("body")
        set_attr("extra", "value")  # must not raise even though it's a no-op
    assert ran == ["body"]


def test_current_trace_id_hex_is_none_before_init():
    tracing._reset_for_tests()
    assert tracing.current_trace_id_hex() is None


def test_enabled_is_false_before_init():
    tracing._reset_for_tests()
    assert tracing.enabled() is False


def test_traced_span_propagates_real_exceptions_from_its_body():
    """Tracing must never SWALLOW a real application error — only its OWN
    export/setup failures are caught (see the module's own docstring)."""
    tracing._reset_for_tests()

    class _Boom(Exception):
        pass

    try:
        with tracing.traced_span("unit.test"):
            raise _Boom("real business error")
    except _Boom:
        pass
    else:
        raise AssertionError("traced_span swallowed a real exception from its body")
