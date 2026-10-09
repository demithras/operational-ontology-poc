"""PROT-H28 R28-7/R28-8 (+ C28-6): retries reuse the SAME cap; duplicates are counted from the ledger only; a replayed request id
never dispatches a second effect; a crash after the world commit resubmits the durable intent with the same chain id."""
from g4_adapters import Duplicate, FalseFailure, Honest, Omission, TimeoutAfterApply
from g4_rig import EXP, G4Rig, RES
from r3_shared import extcap


def test_r28_8_timeout_after_apply_is_resubmitted_with_the_same_cap_and_stays_one_row(tmp_path):
    r = G4Rig(tmp_path, adapter=TimeoutAfterApply)
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        assert r.dep.dispatch_pending().body == {"submitted": 1}              # raises inside the adapter = TIMEOUT
        assert r.dep.dispatch_pending().body == {"submitted": 1}              # resubmission with the same cap: refused, uses_exhausted
        assert r.dep.dispatch_pending().body == {"submitted": 1}              # reply FAILED again; this is the third and last attempt
        assert r.dep.dispatch_pending().body == {"submitted": 0}
        caps = [q.cap for q in r.recorders["ERP"].log]
        assert len(caps) == 3 and len({extcap.chain_id(c) for c in caps}) == 1 and len(set(caps)) == 1
        assert len(r.applied("r1#0")) == 1
        assert [a["reason"] for a in r.ledger()["audit"] if a["outcome"] == "refused"] == ["uses_exhausted"]   # benign refused row
    finally:
        r.finish()


def test_r28_7_negative_failed_replies_are_bounded_and_never_double_apply(tmp_path):
    r = G4Rig(tmp_path, adapter=FalseFailure)                                 # applied, but the reply says FAILED
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        subs = [r.dep.dispatch_pending().body["submitted"] for _ in range(5)]
        assert subs == [1, 1, 1, 0, 0]                                        # MAX_ATTEMPTS submissions, then stop
        assert len(r.applied("r1#0")) == 1                                    # at_most_once: no duplicate beyond the class allowance
        assert len({extcap.chain_id(q.cap) for q in r.recorders["ERP"].log}) == 1
    finally:
        r.finish()


def test_r28_7_adapter_side_duplicate_delivery_is_stopped_by_the_cap(tmp_path):
    r = G4Rig(tmp_path, adapter=Duplicate)
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        r.dep.dispatch_pending()
        assert len(r.applied("r1#0")) == 1                                    # max_uses == 1 for at_most_once
    finally:
        r.finish()


def test_idempotent_set_allows_up_to_three_uses_and_no_more(tmp_path):
    r = G4Rig(tmp_path, per_system={"MES": Duplicate})
    try:
        assert r.call("planner-1", "reschedule_work_order", RES, "r1").status == "OK"
        r.dep.dispatch_pending()
        assert len(r.applied("r1#0")) == 3                                    # harmless repetition of the SAME payload (max_uses 3)
        assert r.settle("r1")[0]["state"] == "RECONCILED_SUCCESS"            # idempotent_set: |M| > 1 is not a duplicate (no D3)
    finally:
        r.finish()


def test_replayed_request_id_never_dispatches_again(tmp_path):
    r = G4Rig(tmp_path)
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        r.dep.dispatch_pending()
        again = r.call("planner-1", "expedite_purchase_order", EXP, "r1")
        assert again.status == "OK" and again.body.get("replayed") is True
        assert r.dep.dispatch_pending().body == {"submitted": 0} and len(r.applied()) == 1 and len(r.recorders["ERP"].log) == 1
    finally:
        r.finish()


def test_omission_is_resubmitted_then_fails_after_the_window(tmp_path):
    r = G4Rig(tmp_path, adapter=Omission)
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        assert [r.dep.dispatch_pending().body["submitted"] for _ in range(4)] == [1, 1, 1, 0]
        assert r.settle("r1")[0]["state"] == "RECONCILED_FAILED" and r.applied() == []
    finally:
        r.finish()


def test_c28_6_crash_after_commit_restart_resubmits_the_same_cap_once(tmp_path):
    r = G4Rig(tmp_path)
    try:
        r.dep.arm_crash("after_commit")
        assert (r.call("planner-1", "expedite_purchase_order", EXP, "r1").status) == "UNKNOWN"
        assert r.recorders["ERP"].log == [] and r.dep.dispatch_pending().status == "UNAVAILABLE"   # crashed: nothing dispatches
        r.dep.restart()
        first = r.dep.outcome("r1")
        assert first.status == "OK" and first.body["outcomes"][0]["state"] == "PENDING"            # the durable intent survived
        assert r.dep.dispatch_pending().body == {"submitted": 1}
        again = r.call("planner-1", "expedite_purchase_order", EXP, "r1")
        assert again.status == "OK" and len(r.applied("r1#0")) == 1                               # no second effect
        assert r.dep.dispatch_pending().body == {"submitted": 0}
        assert r.settle("r1")[0]["state"] == "RECONCILED_SUCCESS"
    finally:
        r.finish()


def test_crash_before_commit_leaves_no_intent_and_no_dispatch(tmp_path):
    r = G4Rig(tmp_path)
    try:
        r.dep.arm_crash("before_commit")
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "UNKNOWN"
        r.dep.restart()
        assert r.dep.outcome("r1").status == "INVALID" and r.dep.dispatch_pending().body == {"submitted": 0}
        assert r.ledger()["effects"] == [] and r.recorders["ERP"].log == []
    finally:
        r.finish()
