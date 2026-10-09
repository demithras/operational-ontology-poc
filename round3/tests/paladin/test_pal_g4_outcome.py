"""PROT-H28 R28-4..R28-6, R28-9/10: outcome records come from the OBSERVER ledger rows only; an adapter's reply is never evidence."""
import pytest

from g4_adapters import (Duplicate, FalseFailure, FalseSuccess, Honest, PayloadMutation, TargetSubstitution, TimeoutAfterApply)
from g4_rig import EXP, G4Rig, RES
from r3_shared.extadapter import AdapterReply
from r3_shared.extobs import ObserverFault
from r3_shared.outcome import allowed_transition, validate_outcomes


def one(r, rid, op="expedite_purchase_order", args=EXP, sub="planner-1"):
    assert r.call(sub, op, args, rid).status == "OK"
    outs = r.settle(rid)
    validate_outcomes({"outcomes": outs})                                   # exact six keys, vocabulary, sorted evidence
    return outs[0]


@pytest.mark.parametrize("adapter,state", [(Honest, "RECONCILED_SUCCESS"), (FalseSuccess, "RECONCILED_FAILED"),
                                           (FalseFailure, "RECONCILED_SUCCESS"), (TargetSubstitution, "DIVERGED"),
                                           (PayloadMutation, "DIVERGED"), (Duplicate, "RECONCILED_SUCCESS"),
                                           (TimeoutAfterApply, "RECONCILED_SUCCESS")])
def test_r28_5_state_follows_the_ledger_not_the_reply(tmp_path, adapter, state):
    r = G4Rig(tmp_path, adapter=adapter)
    try:
        o = one(r, "r1")
        assert (o["state"], o["confidence"]) == (state, "full")
        assert (len(o["evidence"]) > 0) == (adapter is not FalseSuccess)    # evidence = ledger seqs actually used
        assert len(r.applied("r1#0")) == {FalseSuccess: 0, TargetSubstitution: 0, PayloadMutation: 0}.get(adapter, 1)   # ledger truth
    finally:
        r.finish()


def test_r28_6_lying_ok_is_pending_until_the_window_closes_then_failed(tmp_path):
    r = G4Rig(tmp_path, adapter=FalseSuccess)
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        r.dep.dispatch_pending()
        r.tick(4)
        assert r.dep.reconcile("r1", 5).body["outcomes"][0]["state"] == "PENDING"          # window open: never SUCCESS
        assert r.dep.reconcile("r1", 8).body["outcomes"][0]["state"] == "PENDING"          # complete_through == E is not > E
        r.tick(6)
        assert r.dep.reconcile("r1", 10).body["outcomes"][0]["state"] == "RECONCILED_FAILED"
    finally:
        r.finish()


def test_r28_6_divergence_is_absorbing_and_transitions_are_monotone(tmp_path):
    r = G4Rig(tmp_path, adapter=TargetSubstitution)
    try:
        seen = ["PENDING"]
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        r.dep.dispatch_pending()
        for wm in (0, 3, 9, 12):
            r.tick(3)
            seen.append(r.dep.reconcile("r1", wm).body["outcomes"][0]["state"])
        assert seen[-1] == "DIVERGED" and all(allowed_transition(a, b) for a, b in zip(seen, seen[1:]))
        r.observer.fault = ObserverFault.unavailable()
        assert r.dep.reconcile("r1", 20).body["outcomes"][0]["state"] == "DIVERGED"          # rule U keeps a final state
    finally:
        r.finish()


class Delayed(Honest):
    adapter_id = "O2"

    def __init__(self, c):
        super().__init__(c)
        self.held = []

    def submit(self, req):
        self.held.append(req)
        return AdapterReply("OK", {})


def test_delayed_write_in_window_succeeds_and_after_expiry_is_refused_not_success(tmp_path):
    r = G4Rig(tmp_path, adapter=Delayed)
    try:
        for rid in ("in", "late"):
            assert r.call("planner-1", "expedite_purchase_order", {**EXP, "po_id": "PO-992"}, rid).status == "OK"
        r.dep.dispatch_pending()
        held = r.recorders["ERP"].inner.held
        r.tick(3)
        Honest.submit(r.recorders["ERP"].inner, held[0])                                      # tick 3 <= E: applied
        assert r.dep.reconcile("in", 3).body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"
        r.tick(10)
        Honest.submit(r.recorders["ERP"].inner, held[1])                                      # tick 13 > E: refused `expired`
        r.tick(1)
        assert r.dep.reconcile("in", 14).body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"
        assert r.dep.reconcile("late", 14).body["outcomes"][0]["state"] == "RECONCILED_FAILED"   # benign refused row, no success
        assert r.applied("late#0") == [] and [a["reason"] for a in r.ledger()["audit"] if a["correlation"] == "late#0"] == ["expired"]
    finally:
        r.finish()


def test_r28_10_effects_only_system_is_low_confidence_and_hides_refused_attempts(tmp_path):
    r = G4Rig(tmp_path, per_system={"MES": TargetSubstitution})
    try:
        o = one(r, "r1", "reschedule_work_order", RES)
        assert o["confidence"] == "low" and o["state"] == "RECONCILED_FAILED"               # refusal invisible: scope limit L2
        assert [a["reason"] for a in r.ledger()["audit"] if a["correlation"] == "r1#0"] == ["target_mismatch"]   # exists in the ledger
    finally:
        r.finish()
    r = G4Rig(tmp_path / "ok", per_system={"MES": Honest})
    try:
        o = one(r, "r1", "reschedule_work_order", RES)
        assert (o["state"], o["confidence"]) == ("RECONCILED_SUCCESS", "low")
    finally:
        r.finish()


def test_observer_unavailable_and_lagging(tmp_path):
    r = G4Rig(tmp_path, fault=ObserverFault.unavailable())
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        r.dep.dispatch_pending()
        r.tick(10)
        res = r.dep.reconcile("r1", 11)
        assert res.status == "OK" and res.body["outcomes"][0]["state"] == "UNKNOWN"          # rule U, never an error status
        r.observer.fault = ObserverFault.lagging(5)
        assert r.dep.reconcile("r1", 11).body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"   # row tick 0 <= 11-5
        assert r.dep.outcome("r1").body["outcomes"][0]["state"] == "RECONCILED_SUCCESS"      # self-report, no observer read
    finally:
        r.finish()


def test_unknown_request_is_invalid(tmp_path):
    r = G4Rig(tmp_path)
    try:
        for res in (r.dep.reconcile("nope", 3), r.dep.outcome("nope")):
            assert (res.status, res.body) == ("INVALID", {"reason": "unknown_request"})
        r.call("nobody-1", "reschedule_work_order", RES, "denied")                        # a refused request has no outcome
        assert r.dep.outcome("denied").status == "INVALID"
    finally:
        r.finish()
