"""H23 R5-R8: replay/idempotency, commit-time preconditions, explicit outcomes, legitimate progress."""
import copy
import sqlite3
import threading

import pytest

from conv_helpers import SAFE_TRANSFER, VALID, zero_effects
from r3_shared.world import WorldHandle, diff


def _without_grants(auth, operation):
    a = copy.deepcopy(auth)
    a["grants"] = [g for g in a["grants"] if g["operation"] not in (operation, "*")]
    return a


# -- R5 replay and idempotency -----------------------------------------------------------------
def test_r5_committed_request_id_never_produces_a_second_effect(mfg):
    t = mfg.token("planner-1")
    first = mfg.dep.direct(t, "transfer_inventory", SAFE_TRANSFER, request_id="once")
    for _ in range(3):
        again = mfg.dep.call_tool(t, "transfer_inventory", SAFE_TRANSFER, request_id="once")
        assert again.status == "OK" and again.body["replayed"] is True
    assert len(mfg.snap()["effects"]) == 1
    assert first.status == "OK"


def test_r5_same_request_id_with_different_content_is_refused(mfg):
    t = mfg.token("planner-1")
    assert mfg.dep.direct(t, "transfer_inventory", SAFE_TRANSFER, request_id="k").status == "OK"
    with zero_effects(mfg):
        assert mfg.dep.direct(t, "transfer_inventory", {**SAFE_TRANSFER, "quantity": 11}, request_id="k").status == "INVALID"
        assert mfg.dep.direct(mfg.token("admin-1"), "transfer_inventory", SAFE_TRANSFER, request_id="k").status == "INVALID"


def test_r5_replay_after_authority_change_is_decided_against_current_authority(mfg):
    t = mfg.token("planner-1")
    assert mfg.dep.direct(t, "transfer_inventory", SAFE_TRANSFER, request_id="rv").status == "OK"
    mfg.dep.set_authority(_without_grants(mfg.auth, "transfer_inventory"))
    with zero_effects(mfg):
        r = mfg.dep.direct(t, "transfer_inventory", SAFE_TRANSFER, request_id="rv")
        assert r.status == "DENIED"  # NOT the cached first result
        assert mfg.dep.call_tool(t, "transfer_inventory", SAFE_TRANSFER, request_id="rv2").status == "DENIED"
    assert mfg.dep.tools(t) == [t_ for t_ in mfg.dep.tools(t) if t_.name != "transfer_inventory"]


def test_r5_revoked_grant_stops_new_requests_and_regrant_restores(mfg):
    t = mfg.token("planner-1")
    mfg.dep.set_authority(_without_grants(mfg.auth, "transfer_inventory"))
    with zero_effects(mfg):
        assert mfg.dep.direct(t, "transfer_inventory", SAFE_TRANSFER, request_id="n1").status == "DENIED"
    mfg.dep.set_authority(mfg.auth)
    assert mfg.dep.direct(t, "transfer_inventory", SAFE_TRANSFER, request_id="n1").status == "OK"  # denied attempt did not burn the id


def test_r5_concurrent_duplicates_commit_exactly_once(mfg):
    t = mfg.token("planner-1")
    out = []
    ts = [threading.Thread(target=lambda: out.append(mfg.dep.direct(t, "transfer_inventory", SAFE_TRANSFER, request_id="race")))
          for _ in range(12)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    assert [r.status for r in out].count("OK") == 12 and len(mfg.snap()["effects"]) == 1


def test_r5_replay_does_not_leak_first_result_to_another_subject(mfg):
    assert mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", SAFE_TRANSFER, request_id="p").status == "OK"
    r = mfg.dep.direct(mfg.token("nobody-1"), "transfer_inventory", SAFE_TRANSFER, request_id="p")
    assert r.status == "DENIED" and "effects" not in r.body


# -- R6 commit-time preconditions ---------------------------------------------------------------
def test_r6_stock_is_checked_against_the_world_at_commit(mfg):
    t = mfg.token("planner-1")
    assert mfg.dep.direct(t, "transfer_inventory", {**SAFE_TRANSFER, "quantity": 80}, request_id="s1").status == "OK"
    h = mfg.store.handle("probe")
    h.update("InventoryLot", "LOT-B-PX17", {"onHand": 30})  # the world moves between two requests
    h.close()
    with zero_effects(mfg):
        r = mfg.dep.direct(t, "transfer_inventory", {**SAFE_TRANSFER, "quantity": 20}, request_id="s2")
        assert r.status in ("INVALID", "DENIED")


def test_r6_stale_evidence_is_decided_by_the_clock_at_commit(mfg):
    t = mfg.token("planner-1")
    mfg.clock.advance(10)
    with zero_effects(mfg):
        r = mfg.dep.direct(t, "transfer_inventory", SAFE_TRANSFER, request_id="old")
        assert (r.status, r.body["rule"]) == ("DENIED", "transfer-stale-evidence")


def test_r6_quarantine_and_missing_targets_refused(mfg):
    t = mfg.token("planner-1")
    with zero_effects(mfg):
        q = {**SAFE_TRANSFER, "part": "PX-900", "source_warehouse": "WH-A", "destination_warehouse": "WH-B"}
        assert mfg.dep.direct(t, "transfer_inventory", q).body["rule"] == "transfer-quarantine"
        assert mfg.dep.direct(t, "expedite_purchase_order", {"po_id": "PO-NOPE", "expedite_fee": 1}).status == "DENIED"
        assert mfg.dep.direct(t, "reschedule_work_order", {"work_order_id": "WO-NOPE", "new_planned_start": 3}).status in ("DENIED", "INVALID")


def test_r6_caller_supplied_state_is_not_accepted(mfg):
    with zero_effects(mfg):
        for extra in ({"onHand": 10_000}, {"phase": "DRAFT"}, {"approved": True}, {"state": {"WH-B": 10_000}}):
            r = mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", {**SAFE_TRANSFER, "quantity": 500, **extra})
            assert r.status == "INVALID" and r.body["reason"] == "unknown_field"


@pytest.mark.parametrize("op,args", [
    ("start_run", {"hypothesis": "H-A"}),                 # DRAFT, not PREREGISTERED
    ("start_run", {"hypothesis": "H-NOPE"}),              # missing target
    ("preregister_hypothesis", {"hypothesis": "H-B", "freeze_hash": "x"}),  # already PREREGISTERED
    ("supersede_hypothesis", {"hypothesis": "H-A", "successor": "H-E"}),   # not EVALUATED
    ("edit_threshold", {"threshold": "T-B", "value": 1}),  # governed hypothesis not DRAFT
    ("attach_evidence", {"hypothesis": "H-C", "evidence": "EV-C-BAD"}),    # version not pinned to a tested experiment
    ("flag_orphan_component", {"component": "cmp-live"}),
    ("create_hypothesis", {"claim": "ephemeral:secret"}),
])
def test_r6_project_world_state_gates_commit(proj, op, args):
    with zero_effects(proj):
        assert proj.dep.direct(proj.token("researcher-1"), op, args).status in ("INVALID", "DENIED")


def test_r6_evaluation_without_evidence_is_allowed_only_with_a_machine_reason(proj):
    r = proj.dep.direct(proj.token("researcher-1"), "evaluate_hypothesis", {"hypothesis": "H-F"})
    assert r.status == "OK"  # no evidence, but derive_verdict is INCONCLUSIVE: a reason exists
    v = proj.snap()["objects"]["Verdict:verdict-H-F-1"]["props"]
    assert v["value"] == "INCONCLUSIVE" and "evidence_count=0" in v["reason"]


# -- R7 explicit outcomes ------------------------------------------------------------------------
def test_r7_outcome_classes_are_distinct(mfg):
    t = mfg.token("planner-1")
    with zero_effects(mfg):
        assert mfg.dep.direct(mfg.token("nobody-1"), "transfer_inventory", SAFE_TRANSFER).status == "DENIED"
        assert mfg.dep.direct(t, "transfer_inventory", {"part": "PX-17"}).status == "INVALID"            # schema
        assert mfg.dep.direct(t, "transfer_inventory", {**SAFE_TRANSFER, "quantity": True}).status == "INVALID"
        assert mfg.dep.direct(t, "transfer_inventory", {**SAFE_TRANSFER, "quantity": 0}).status == "INVALID"  # precondition
        assert mfg.dep.direct(t, "transfer_inventory", {**SAFE_TRANSFER, "destination_warehouse": "WH-B"}).status == "INVALID"
        mfg.dep.set_dependency_down("WMS")
        r = mfg.dep.direct(t, "transfer_inventory", SAFE_TRANSFER, request_id="down")
        assert r.status == "UNAVAILABLE"
    mfg.dep.set_dependency_down("WMS", False)
    assert mfg.dep.direct(t, "transfer_inventory", SAFE_TRANSFER, request_id="down").status == "OK"  # failure did not burn the id


def test_r7_error_midway_commits_no_partial_effect(proj, monkeypatch):
    real, calls = WorldHandle.link, []

    def flaky(self, *a):
        calls.append(a)
        if len(calls) == 2:
            raise sqlite3.OperationalError("disk I/O error")
        return real(self, *a)

    monkeypatch.setattr(WorldHandle, "link", flaky)
    with zero_effects(proj):  # attach_evidence writes two links; the second fails -> the first must roll back
        r = proj.dep.direct(proj.token("researcher-1"), "attach_evidence", VALID["attach_evidence"], request_id="half")
        assert r.status == "UNAVAILABLE" and len(calls) == 2
    monkeypatch.undo()
    assert proj.dep.direct(proj.token("researcher-1"), "attach_evidence", VALID["attach_evidence"], request_id="half").status == "OK"


def test_r7_rejected_effect_rolls_back_whole_request(proj):
    h = proj.store.handle("probe")
    h.create("Experiment", "E-B@v2", {"version": "2", "evaluator_ref": "x", "evidence_schema_ref": "y"})  # new id now taken
    h.close()
    with zero_effects(proj):
        r = proj.dep.direct(proj.token("researcher-1"), "new_experiment_version", VALID["new_experiment_version"])
        assert r.status == "DENIED" and r.body["rule"] == "new-version-must-be-new"


def test_r7_approval_required_is_an_explicit_denial_not_a_pending_effect(mfg):
    h = mfg.store.handle("probe")
    h.update("InventoryLot", "LOT-B-PX17", {"onHand": 900})
    h.close()
    with zero_effects(mfg):
        r = mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", {**SAFE_TRANSFER, "quantity": 200}, request_id="ap")
        assert (r.status, r.body["reason"]) == ("DENIED", "approval_required")
        r = mfg.dep.direct(mfg.token("planner-1"), "reschedule_work_order", {"work_order_id": "WO-42", "new_planned_start": 50})
        assert (r.status, r.body["reason"]) == ("DENIED", "approval_required")


# -- R8 legitimate progress ------------------------------------------------------------------------
def test_r8_every_allowed_valid_request_commits(make):
    cases = [("manufacturing", "planner-1", o) for o in ("transfer_inventory", "expedite_purchase_order", "reschedule_work_order")]
    cases += [("manufacturing", "admin-1", o) for o in ("expedite_purchase_order", "reschedule_work_order")]
    cases += [("project", "admin-1", o) for o in VALID if o not in ("transfer_inventory", "expedite_purchase_order", "reschedule_work_order")]
    cases += [("project", "agent-evidence-1", "start_run"), ("project", "agent-evidence-1", "attach_evidence"),
              ("project", "agent-draft-1", "create_hypothesis"), ("project", "agent-draft-1", "record_decision")]
    for domain, who, op in cases:
        rig = make(domain)
        args = VALID[op] if op != "start_run" else {"hypothesis": "H-B"}
        before = rig.snap()
        r = rig.dep.direct(rig.token(who), op, args, request_id=f"{who}-{op}")
        assert r.status == "OK", (domain, who, op, r)
        assert diff(before, rig.snap()), (who, op)
