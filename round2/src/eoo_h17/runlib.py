"""Run a state machine through Hypothesis with a fixed seed, collecting per-example trace records."""
from __future__ import annotations

from hypothesis import HealthCheck, Phase, seed as hseed, settings
from hypothesis.stateful import get_state_machine_test

from .machine import make_machine

SUPPRESS = list(HealthCheck)


def new_sink() -> dict:
    return {"records": [], "failures": []}


def run_machine(domain: str, seed: int, max_examples: int, step_count: int = 14, sink: dict | None = None,
                phases=(Phase.generate, Phase.shrink)) -> dict:
    """Run ``max_examples`` examples. Returns the sink; a Hypothesis failure is caught and recorded (not raised)."""
    sink = sink if sink is not None else new_sink()
    machine = make_machine(domain, sink)
    st = settings(max_examples=max_examples, stateful_step_count=step_count, deadline=None, database=None,
                  suppress_health_check=SUPPRESS, phases=phases, report_multiple_bugs=False, derandomize=False)
    test = get_state_machine_test(machine, settings=st, _min_steps=0, _flaky_state={"selecting_rule": False})
    try:
        hseed(seed)(test)()
    except BaseException as exc:  # noqa: BLE001 - a counterexample is a RESULT; anything else is re-raised below
        sink["exception"] = {"type": type(exc).__name__, "message": str(exc)[:600],
                             "notes": [str(n)[:2000] for n in getattr(exc, "__notes__", [])][:6]}
        if not sink["failures"]:
            raise
    return sink


def unique(sink: dict) -> int:
    return len({r["sha"] for r in sink["records"] if r["n_steps"] > 0})
