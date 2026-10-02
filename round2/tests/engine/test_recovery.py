"""Crash simulation: drop the Engine object, rebuild from the JSONL journal, recover deterministically."""
import shutil

import pytest

from eoo_engine import SimulatedCrash
from synth import Clock, FakeCarrier, build, effects_of


def _crash(tmp_path, fault, action="ship_box", inputs=None, mode="confirm"):
    carrier = FakeCarrier(mode)
    j = tmp_path / "journal.jsonl"
    eng, k, _ = build(carrier=carrier, journal=j, faults={fault})
    with pytest.raises(SimulatedCrash):
        eng.propose(action, inputs or {"box": "b1"}, "filler", idempotency_key="k")
    del eng  # the process "dies": only the journal and the external system survive
    return j, k, carrier


def _rebuild(j, k, carrier):
    eng, _, _ = build(k=k, carrier=carrier, journal=j, seed=False, register=False, clock=Clock())
    return eng


def test_crash_after_executing_then_recover_exactly_once(tmp_path):
    j, k, carrier = _crash(tmp_path, "EXECUTING")
    eng = _rebuild(j, k, carrier)
    rec = eng.executions["x1"]
    assert rec["state"] == "EXECUTING" and carrier.calls == [] and effects_of(eng, "x1") == ()
    report = eng.recover()
    assert report == [{"exec": "x1", "from": "EXECUTING", "to": "RECONCILED_SUCCESS"}]
    assert len(carrier.calls) == 1 and len(effects_of(eng, "x1")) == 1
    again = eng.propose("ship_box", {"box": "b1"}, "filler", idempotency_key="k")
    assert again == eng.executions["x1"] and again["exec"] == "x1"  # v1.1: snapshot equality, not identity
    assert len(carrier.calls) == 1


def test_crash_after_effects_committed_then_recover(tmp_path):
    j, k, carrier = _crash(tmp_path, "EFFECTS_COMMITTED")
    eng = _rebuild(j, k, carrier)
    assert eng.executions["x1"]["state"] == "EFFECTS_COMMITTED" and len(effects_of(eng, "x1")) == 1
    assert eng.recover() == [{"exec": "x1", "from": "EFFECTS_COMMITTED", "to": "RECONCILED_SUCCESS"}]
    assert len(carrier.calls) == 1 and len(effects_of(eng, "x1")) == 1


def test_crash_after_canonical_commit_keeps_store_state(tmp_path):
    j, k, carrier = _crash(tmp_path, "EFFECTS_COMMITTED", action="fill_box", inputs={"box": "b1", "amount": 5})
    eng = _rebuild(j, k, carrier)
    assert eng.get("Box", "b1")["props"]["level"] == 15
    eng.recover()
    assert eng.get("Box", "b1")["props"]["level"] == 15 and len(effects_of(eng, "x1")) == 1
    assert eng.executions["x1"]["state"] == "RECONCILED_SUCCESS"


def test_crash_between_intent_and_response_is_outcome_unknown(tmp_path):
    j, k, carrier = _crash(tmp_path, "ext_intent")
    eng = _rebuild(j, k, carrier)
    assert eng.recover() == [{"exec": "x1", "from": "EXECUTING", "to": "OUTCOME_UNKNOWN"}]
    assert carrier.calls == []  # never re-called blindly


def test_crash_after_response_resumes_without_second_call(tmp_path):
    j, k, carrier = _crash(tmp_path, "ext_response")
    assert len(carrier.calls) == 1
    eng = _rebuild(j, k, carrier)
    eng.recover()
    assert len(carrier.calls) == 1 and eng.executions["x1"]["state"] == "RECONCILED_SUCCESS"
    assert len(effects_of(eng, "x1")) == 1


@pytest.mark.parametrize("fault", ["EXECUTING", "EFFECTS_COMMITTED", "ext_intent", "ext_response", "PROPOSED",
                                   "APPROVED"])
def test_recovery_is_deterministic(tmp_path, fault):
    j, k, carrier = _crash(tmp_path, fault)
    copy = tmp_path / "copy.jsonl"
    shutil.copy(j, copy)
    calls = list(carrier.calls)
    a = _rebuild(j, k, carrier)
    a.recover()
    carrier.calls[:] = calls
    b = _rebuild(copy, k, carrier)
    b.recover()
    assert a.fingerprint() == b.fingerprint()
    assert a.state().state_hash() == b.state().state_hash()


def test_replay_without_crash_reproduces_state(tmp_path):
    j = tmp_path / "j.jsonl"
    eng, k, carrier = build(journal=j)
    eng.propose("fill_box", {"box": "b1", "amount": 5}, "filler", idempotency_key="a")
    eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="b")
    eng.propose("make_box", {"key": "z", "level": 2}, "filler")
    again = _rebuild(j, k, carrier)
    assert again.fingerprint() == eng.fingerprint()


def test_crash_after_proposed_recovers_by_deciding_gates(tmp_path):
    j, k, carrier = _crash(tmp_path, "PROPOSED")
    eng = _rebuild(j, k, carrier)
    assert eng.executions["x1"]["state"] == "PROPOSED"
    assert eng.recover() == [{"exec": "x1", "from": "PROPOSED", "to": "RECONCILED_SUCCESS"}]
    assert len(carrier.calls) == 1 and len(effects_of(eng, "x1")) == 1
