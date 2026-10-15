"""R8 legitimate progress: every operation succeeds for an authorized principal, with its specified effects in the world."""
import pytest

from r3_shared.world import diff

MFG = [
    ("planner-1", "transfer_inventory", {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 10},
     lambda e: e[0]["kind"] == "external" and e[0]["ref"].startswith("WMS:transfer") and e[0]["payload"]["quantity"] == 10),
    ("planner-1", "expedite_purchase_order", {"po_id": "PO-991", "expedite_fee": 100},
     lambda e: e[0]["ref"].startswith("ERP:expedite")),
    ("planner-1", "reschedule_work_order", {"work_order_id": "WO-43", "new_planned_start": 35},
     lambda e: e[0]["ref"].startswith("MES:reschedule") and e[0]["payload"]["new_planned_start"] == 35),
]
PROJ = [
    ("researcher-1", "create_hypothesis", {"claim": "a new claim"}, lambda e: e[0]["kind"] == "create" and e[0]["ref"].startswith("Hypothesis:hyp-")),
    ("researcher-1", "edit_threshold", {"threshold": "T-A", "value": {"min": 11}}, lambda e: e[0]["changes"]["value"] == [{"min": 10}, {"min": 11}]),
    ("researcher-1", "preregister_hypothesis", {"hypothesis": "H-A", "freeze_hash": "abc123"},
     lambda e: e[0]["changes"]["phase"] == ["DRAFT", "PREREGISTERED"]),
    ("researcher-1", "new_experiment_version", {"experiment": "E-B@v1", "contract_version": "CV-1"},
     lambda e: {x["ref"] for x in e} >= {"Experiment:E-B@v2", "ContractVersion:CV-1+2"}),
    ("researcher-1", "start_run", {"hypothesis": "H-B"}, lambda e: e[0]["changes"]["phase"] == ["PREREGISTERED", "RUNNING"]),
    ("researcher-1", "attach_evidence", {"hypothesis": "H-C", "evidence": "EV-C2"},
     lambda e: {x["kind"] for x in e} == {"link"} and len(e) == 2),
    ("researcher-1", "evaluate_hypothesis", {"hypothesis": "H-C"},
     lambda e: any(x["ref"] == "Verdict:verdict-H-C-1" and x["props"]["value"] == "SUPPORTED" for x in e)),
    ("researcher-1", "supersede_hypothesis", {"hypothesis": "H-D", "successor": "H-E"},
     lambda e: any(x["ref"].startswith("SUPERSEDED_BY|Hypothesis:H-D") for x in e)),
    ("researcher-1", "record_decision", {"decision": "DEC-1", "contract_version": "CV-1"},
     lambda e: [x["ref"] for x in e] == ["CHANGES|Decision:DEC-1|ContractVersion:CV-1"]),
    ("researcher-1", "flag_orphan_component", {"component": "cmp-orphan"}, lambda e: e[0]["changes"]["orphan_flagged"] == [False, True]),
]


def _run(rig, who, op, args, check):
    before = rig.snap()
    r = rig.dep.call_tool(rig.token(who), op, args, request_id=f"fn-{op}")
    assert r.status == "OK", (op, r)
    effects = diff(before, rig.snap())
    assert effects and check(effects), (op, effects)


@pytest.mark.parametrize("who,op,args,check", MFG, ids=[m[1] for m in MFG])
def test_manufacturing_operation_commits(mfg, who, op, args, check):
    _run(mfg, who, op, args, check)


@pytest.mark.parametrize("who,op,args,check", PROJ, ids=[m[1] for m in PROJ])
def test_project_operation_commits(proj, who, op, args, check):
    _run(proj, who, op, args, check)


def test_every_spec_operation_is_covered(mfg, proj):
    covered = {m[1] for m in MFG} | {m[1] for m in PROJ}
    assert covered == {o["name"] for o in mfg.ops["operations"]} | {o["name"] for o in proj.ops["operations"]}


def test_delegated_agent_acts_for_planner(mfg):
    args = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 10}
    r = mfg.dep.call_tool(mfg.token("agent-1"), "transfer_inventory", args, on_behalf_of="planner-1", request_id="d1")
    assert r.status == "OK"
    assert len(mfg.snap()["effects"]) == 1


def test_large_transfer_needs_a_valid_independent_approval(mfg):
    args = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 100}
    mfg.clock.advance(0)
    # raise stock first so safety stock does not bind: use a bigger lot via a fresh high-stock part
    h = mfg.store.handle("seed")
    h.update("InventoryLot", "LOT-B-PX17", {"onHand": 400})
    h.close()
    t = mfg.token("planner-1")
    before = mfg.snap()
    assert mfg.dep.direct(t, "transfer_inventory", args, request_id="big").body["reason"] == "approval_required"
    assert diff(before, mfg.snap()) == []
    assert mfg.dep.approve(mfg.token("planner-1"), "transfer_inventory", args, "planner-1").status == "DENIED"  # self-approval
    assert mfg.dep.approve(mfg.token("senior-1"), "transfer_inventory", {**args, "quantity": 99}, "planner-1").status == "OK"
    assert mfg.dep.direct(t, "transfer_inventory", args, request_id="big").status == "DENIED"  # bound to exact inputs
    assert mfg.dep.approve(mfg.token("senior-1"), "transfer_inventory", args, "planner-1").status == "OK"
    assert mfg.dep.direct(t, "transfer_inventory", args, request_id="big").status == "OK"
    assert len(diff(before, mfg.snap())) == 1
    assert mfg.dep.direct(t, "transfer_inventory", args, request_id="big2").status == "DENIED"  # approval is single-use


def test_reads_return_values_and_missing_is_unknown(mfg):
    t = mfg.token("planner-1")
    assert mfg.dep.read(t, "get", {"type": "Warehouse", "key": "WH-A"}).body["props"]["warehouseId"] == "WH-A"
    assert mfg.dep.read(t, "get", {"type": "Warehouse", "key": "nope"}).body == {"reason": "not_found"}  # P1e-5 / Q12
    assert mfg.dep.read(t, "resolve_canonical_id", {"source_local_id": "SKU-88429"}).body["value"] == "PX-17"
    assert mfg.dep.read("garbage", "get", {"type": "Warehouse", "key": "WH-A"}).status == "DENIED"


# -- P1b delegate semantics: a delegate is ALWAYS evaluated as its delegator's delegate --------------------------
def _xfer(src, dst):
    return {"part": "PX-17", "source_warehouse": src, "destination_warehouse": dst, "quantity": 1}


@pytest.mark.parametrize("src,dst", [("WH-A", "WH-B"), ("WH-A", "WH-C"), ("WH-B", "WH-C")])
def test_orphan_agent_denied_with_zero_effects(mfg, src, dst):
    before = mfg.snap()
    r = mfg.dep.direct(mfg.token("agent-orphan"), "transfer_inventory", _xfer(src, dst), request_id=f"o-{src}-{dst}")
    assert r.status == "DENIED"
    assert diff(before, mfg.snap()) == []


def test_delegate_without_on_behalf_of_is_evaluated_as_delegate(mfg):
    r = mfg.dep.direct(mfg.token("agent-1"), "transfer_inventory", _xfer("WH-A", "WH-B"), request_id="d1")
    assert r.status == "OK"
    before = mfg.snap()
    r = mfg.dep.direct(mfg.token("agent-hostile-1"), "transfer_inventory", _xfer("WH-B", "WH-A"), request_id="d2")
    assert r.status == "DENIED" and diff(before, mfg.snap()) == []
    r = mfg.dep.direct(mfg.token("agent-1"), "transfer_inventory", _xfer("WH-A", "WH-C"), on_behalf_of="senior-1", request_id="d3")
    assert r.status == "DENIED" and diff(before, mfg.snap()) == []  # on_behalf_of != delegator
