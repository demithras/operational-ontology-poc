"""Manufacturing end to end on the unchanged Engine. Every negative path asserts zero effects."""
from __future__ import annotations

import pytest

from eoo_engine import CapabilityError, Principal

from mfg_helpers import (LATER, NOW, Snap, failed_gates, gate, make, propose_transfer, seed_with, transfer_inputs)


def test_risk_function_canonical_incident():
    e, _, _ = make()
    assert dict(e.call_function("work_order_risk", {"work_order": "WO-42"})) == \
        {"work_order_id": "WO-42", "shortage": 60, "at_risk": True}
    assert e.call_function("work_order_risk", {"work_order": "WO-43"})["at_risk"] is False


def test_transfer_allowed_executes_and_reconciles():
    e, wms, _ = make()
    before = wms.stock[("PX-900", "WH-C")]
    rec = propose_transfer(e)
    assert rec["state"] == "RECONCILED_SUCCESS", rec["gates"]
    assert [g["gate"] for g in rec["gates"]][:5] == ["identity", "inputs", "authority", "preconditions", "policy"]
    assert wms.stock[("PX-900", "WH-C")] == before - 60 and wms.stock[("PX-900", "WH-B")] == 70
    assert len(e.effect_log.entries()) == 1 and len(wms.calls) == 1
    assert rec["observed"]["verdict"] is True and rec["soft_flags"] == []
    assert rec["observations"][0]["observation"]["data"]["transferStatus"] == "COMMITTED"


def test_junior_over_threshold_requires_approval_then_senior_approves():
    e, wms, _ = make()
    rec = propose_transfer(e, who="junior-1", quantity=100)
    assert rec["state"] == "PENDING_APPROVAL"
    zero = Snap(e, wms)
    assert zero.calls == 0 and zero.effects == 0
    x = rec["exec"]
    with pytest.raises(CapabilityError):  # a bare supervisor no longer approves (authorization model v2)
        e.approve(x, "supervisor-1")
    with pytest.raises(CapabilityError):  # nobody approves their own request
        e.approve(x, "junior-1")
    assert e.executions[x]["state"] == "PENDING_APPROVAL" and zero.unchanged()
    done = e.approve(x, "senior-1")
    assert done["state"] == "RECONCILED_SUCCESS"
    assert done["approvals"][0]["pid"] == "senior-1" and done["approvals"][0]["granted"] == ["approval:large_transfer"]
    assert len(wms.calls) == 1 and wms.records[x]["actualQuantity"] == 100
    assert [s for s in done["history"]] == ["PROPOSED", "PENDING_APPROVAL", "APPROVED", "EXECUTING", "EFFECTS_COMMITTED",
                                            "RECONCILED_SUCCESS"]
    assert done["soft_flags"] and done["soft_flags"][0]["constraint"] == "transfer-approval-threshold"


def test_rejected_approval_denies_with_zero_effects():
    e, wms, _ = make()
    rec = propose_transfer(e, who="junior-1", quantity=100)
    z = Snap(e, wms)
    assert e.reject(rec["exec"], "senior-1")["state"] == "DENIED" and z.unchanged()


def test_high_priority_protection_denies_junior_but_not_planner():
    ex = dict(source_warehouse="WH-B", destination_warehouse="WH-A", part="PX-17", quantity=60)
    e, wms, _ = make()
    z = Snap(e, wms)
    rec = propose_transfer(e, who="junior-1", **ex)
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["policy"] and z.unchanged()
    assert gate(rec, "policy")["detail"]["results"][0]["applies"] is True  # hard_deny applied
    e2, wms2, _ = make()
    assert propose_transfer(e2, who="planner-1", **ex)["state"] == "RECONCILED_SUCCESS"
    assert wms2.records["x1"]["actualQuantity"] == 60


def test_protection_control_same_route_not_high_priority_junior_allowed():
    def low(s):
        for o in s["ops"]:
            if o["op"] == "create" and o["key"] == "WO-42":
                o["props"]["priority"] = "MEDIUM"
    e, wms, _ = make(seed_with(low))
    rec = propose_transfer(e, who="junior-1", source_warehouse="WH-B", destination_warehouse="WH-A", part="PX-17", quantity=60)
    assert rec["state"] == "RECONCILED_SUCCESS"


def test_idempotent_retry_same_result_one_effect():
    e, wms, _ = make()
    a = propose_transfer(e, key="same")
    b = propose_transfer(e, key="same")
    assert b["exec"] == a["exec"] and b["state"] == "RECONCILED_SUCCESS"
    assert len(wms.calls) == 1 and len(e.effect_log.entries()) == 1 and wms.stock[("PX-900", "WH-B")] == 70
    z = Snap(e, wms)
    c = propose_transfer(e, key="same", quantity=61)  # same key, different intent
    assert c["state"] == "DENIED" and failed_gates(c) == ["idempotency"] and z.unchanged()


def test_missing_idempotency_key_denied():
    e, wms, _ = make()
    z = Snap(e, wms)
    rec = e.propose("transfer_inventory", transfer_inputs(), "planner-1")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["request"] and z.unchanged()


def test_commit_without_response_is_outcome_unknown_then_reconciles():
    e, wms, _ = make()
    wms.mode = "commit_no_response"
    rec = propose_transfer(e)
    x = rec["exec"]
    assert rec["state"] == "OUTCOME_UNKNOWN" and len(e.effect_log.entries()) == 0
    assert wms.stock[("PX-900", "WH-B")] == 70  # the effect really happened in WMS
    assert rec["adapter_errors"] and "WmsUnavailable" in rec["adapter_errors"][0]["error"]
    wms.cdc_visible = False  # CDC lag: still unknown, no fabricated success
    assert e.reconcile(x)["state"] == "OUTCOME_UNKNOWN"
    wms.cdc_visible = True
    done = e.reconcile(x)
    assert done["state"] == "RECONCILED_SUCCESS" and wms.stock[("PX-900", "WH-B")] == 70 and len(wms.calls) == 1


def test_timeout_without_effect_never_reconciles_to_success():
    e, wms, _ = make()
    wms.mode = "timeout"
    x = propose_transfer(e)["exec"]
    assert e.executions[x]["state"] == "OUTCOME_UNKNOWN" and wms.stock[("PX-900", "WH-B")] == 10
    assert e.reconcile(x)["state"] == "OUTCOME_UNKNOWN" and e.reconcile(x)["observed"]["observation_count"] == 0


@pytest.mark.parametrize("mode", ["reject", "partial", "wrong_quantity"])
def test_wms_divergence_reconciles_to_failed(mode):
    e, wms, _ = make()
    wms.mode = mode
    assert propose_transfer(e)["state"] == "RECONCILED_FAILED"


@pytest.mark.parametrize("who,over,gate_name,clock", [
    ("planner-1", dict(destination_warehouse="WH-A"), "policy", NOW),              # quarantined destination lot
    ("planner-1", dict(source_warehouse="WH-B", destination_warehouse="WH-C", part="PX-17", quantity=100), "policy", NOW),  # safety stock
    ("planner-1", dict(), "policy", LATER),                                         # stale evidence
    ("planner-1", dict(quantity=0), "preconditions", NOW),
    ("planner-1", dict(destination_warehouse="WH-C"), "preconditions", NOW),       # source == destination
    ("planner-1", dict(quantity=501), "preconditions", NOW),                        # more than available
    ("stranger", dict(), "authority", NOW),                                         # no relation on the warehouses
    ("agent-orphan", dict(), "authority", NOW),                                     # delegator holds no relation
    ("ghost", dict(), "identity", NOW),
])
def test_negative_paths_have_zero_effects(who, over, gate_name, clock):
    e, wms, _ = make(clock=clock)
    if who == "stranger":
        e.register_principal(Principal("stranger", frozenset({"planner"}), frozenset()))
    z = Snap(e, wms)
    rec = propose_transfer(e, who=who, **over)
    assert rec["state"] == "DENIED" and failed_gates(rec) == [gate_name], rec["gates"]
    assert z.unchanged() and len(e.effect_log.entries()) == 0


def test_agent_with_delegation_acts_within_delegator_authority():
    e, wms, _ = make()
    rec = propose_transfer(e, who="agent-1")
    assert rec["state"] == "RECONCILED_SUCCESS" and rec["principal"]["delegated_by"]["pid"] == "planner-1"


def test_unknown_part_or_warehouse_is_an_input_error_with_zero_effects():
    e, wms, _ = make()
    z = Snap(e, wms)
    rec = propose_transfer(e, part="NOPE")
    assert rec["state"] == "DENIED" and failed_gates(rec) == ["inputs"] and z.unchanged()
