"""Model-based/stateful test — docs/experiment/spec/08_test_strategy.md
"Level 4 — Stateful/model-based tests" and "Stateful testing".

Runs the shared rule set (tests/model/_machine.py) with an EMPTY bug set:
this is the "the suite is clean against correct behavior" baseline that
tests/model/test_bug_detection.py contrasts against (a suite that fails here
would be useless as an oracle).
"""

from __future__ import annotations

from hypothesis import settings
from hypothesis.stateful import run_state_machine_as_test

from reference_model.state import NO_BUGS

from ._machine import make_machine


def test_stateful_transfer_machine_no_bugs_stays_clean():
    machine_cls = make_machine(NO_BUGS, name="CleanTransferMachine")
    run_state_machine_as_test(
        machine_cls,
        settings=settings(max_examples=80, stateful_step_count=25),
    )
