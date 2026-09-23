"""Bug-injection / mutation-detection test —
docs/experiment/spec/12_implementation_plan.md Phase 1 exit criterion
("shrinking produces minimal failures when deliberate bug injected") and
docs/experiment/spec/08_test_strategy.md "Mutation testing".

For EACH flag in `reference_model.state.ALL_BUGS`, run the shared stateful
machine (tests/model/_machine.py) with exactly that one bug active and
assert Hypothesis finds a failing example. `derandomize=True` pins
Hypothesis's internal random source to a value derived from the test
identity, so the same bug always shrinks to the same minimal failing step
sequence on every run — this is what "reproducible" means here, not a fixed
external seed (Hypothesis's stateful engine does not take one directly).

The shrunk failing sequence for each bug is written to
experiments/exp-000/results/shrunk-failures/<bug>.txt for the experiment
record.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import settings
from hypothesis.stateful import run_state_machine_as_test

from reference_model.state import ALL_BUGS

from ._machine import make_machine

RESULTS_DIR = (
    Path(__file__).resolve().parents[2] / "experiments" / "exp-000" / "results" / "shrunk-failures"
)


def _run_bugged_machine(bug_name: str):
    machine_cls = make_machine(frozenset({bug_name}), name=f"Bugged_{bug_name}")
    run_state_machine_as_test(
        machine_cls,
        settings=settings(max_examples=200, stateful_step_count=25, derandomize=True),
    )


def _write_shrunk_failure(bug_name: str, exc: AssertionError) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"{bug_name}.txt"
    notes = list(getattr(exc, "__notes__", None) or [])
    lines = [
        f"bug: {bug_name}",
        f"assertion: {exc}",
        "",
        "shrunk minimal failing step sequence (Hypothesis stateful, derandomize=True):",
        *notes,
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


@pytest.mark.parametrize("bug_name", sorted(ALL_BUGS))
def test_each_injected_bug_is_found_and_shrunk(bug_name):
    with pytest.raises(AssertionError) as excinfo:
        _run_bugged_machine(bug_name)

    out_path = _write_shrunk_failure(bug_name, excinfo.value)
    assert out_path.exists()
    assert out_path.stat().st_size > 0
