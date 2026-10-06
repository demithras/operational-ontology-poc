"""Functional: every ops-spec operation commits its specified effects for an authorized principal (measured from the world)."""
import pytest

TR = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
def wms(a):  # ops-spec WMS effect payload for a transfer
    return {"source": a["source_warehouse"], "destination": a["destination_warehouse"], "part": a["part"], "quantity": a["quantity"]}


MFG_OK = [("transfer_inventory", TR, "WMS", "transfer"),
          ("expedite_purchase_order", {"po_id": "PO-992", "expedite_fee": 100}, "ERP", "expedite"),
          ("reschedule_work_order", {"work_order_id": "WO-43", "new_planned_start": 55}, "MES", "reschedule")]


@pytest.mark.parametrize("op,args,adapter,target", MFG_OK)
def test_manufacturing_ops_commit_external_effect(mfg, op, args, adapter, target):
    res, eff = mfg.effects_of(lambda: mfg.dep.direct(mfg.token("planner-1"), op, args, request_id="r1"))
    assert res.status == "OK", res
    assert [(e["kind"], e["writer"], e["ref"].split("#")[0]) for e in eff] == [("external", adapter, f"{adapter}:{target}")]
    assert eff[0]["payload"] == (wms(args) if op == "transfer_inventory" else args) and eff[0]["idempotency_key"] == "r1"


def test_manufacturing_transfer_via_tool_and_delegation(mfg):
    tok = mfg.token("agent-1")
    res, eff = mfg.effects_of(lambda: mfg.dep.call_tool(tok, "transfer_inventory", TR, on_behalf_of="planner-1", request_id="r1"))
    assert res.status == "OK" and len(eff) == 1 and eff[0]["payload"] == wms(TR)


def test_manufacturing_large_transfer_needs_a_second_principals_preapproval(mfg):
    big = {**TR, "quantity": 400}
    tok = mfg.token("planner-1")
    res, eff = mfg.effects_of(lambda: mfg.dep.direct(tok, "transfer_inventory", big, request_id="r9"))
    assert (res.status, res.body["reason"], eff) == ("DENIED", "approval_required", [])
    assert mfg.dep.approve(mfg.token("planner-1"), "transfer_inventory", big, "planner-1").status == "DENIED"  # requester
    assert mfg.dep.approve(mfg.token("junior-1"), "transfer_inventory", big, "planner-1").status == "DENIED"   # no capability
    assert mfg.dep.approve(mfg.token("agent-1"), "transfer_inventory", big, "planner-1").status == "DENIED"    # requester's delegate
    assert mfg.snap() == mfg.snap()
    assert mfg.dep.approve(mfg.token("senior-1"), "transfer_inventory", big, "planner-1").status == "OK"
    res, eff = mfg.effects_of(lambda: mfg.dep.direct(tok, "transfer_inventory", big, request_id="r10"))
    assert res.status == "OK" and len(eff) == 1 and eff[0]["payload"] == wms(big)


def test_delegate_request_is_the_same_with_and_without_on_behalf_of(mfg):
    big = {**TR, "quantity": 400}
    assert mfg.dep.approve(mfg.token("senior-1"), "transfer_inventory", big, "agent-1", on_behalf_of="planner-1").status == "OK"
    res, eff = mfg.effects_of(lambda: mfg.dep.direct(mfg.token("agent-1"), "transfer_inventory", big, request_id="d1"))
    assert res.status == "OK" and len(eff) == 1  # approval named on_behalf_of; the call omitted it: same request


PROJ_OK = [("create_hypothesis", {"claim": "brand new claim"}, [("create", "Hypothesis:hyp-86776797c2")]),
           ("edit_threshold", {"threshold": "T-A", "value": {"min": 11}}, [("update", "Threshold:T-A")]),
           ("preregister_hypothesis", {"hypothesis": "H-A", "freeze_hash": "a" * 64}, [("update", "Hypothesis:H-A")]),
           ("new_experiment_version", {"experiment": "E-C@v1", "contract_version": "CV-1"},
            [("create", "ContractVersion:CV-1+2"), ("create", "Experiment:E-C@v2"),
             ("link", "NEW_VERSION_OF|Experiment:E-C@v2|Experiment:E-C@v1")]),
           ("start_run", {"hypothesis": "H-B"}, [("update", "Hypothesis:H-B")]),
           ("attach_evidence", {"hypothesis": "H-F", "evidence": "EV-C2"},
            [("link", "PRODUCES|Experiment:E-F@v1|Evidence:EV-C2"), ("link", "SUPPORTS_OR_REFUTES|Evidence:EV-C2|Hypothesis:H-F")]),
           ("evaluate_hypothesis", {"hypothesis": "H-C"},
            [("create", "Verdict:verdict-H-C-1"), ("link", "EVALUATES|Verdict:verdict-H-C-1|Hypothesis:H-C"),
             ("update", "Hypothesis:H-C")]),
           ("supersede_hypothesis", {"hypothesis": "H-D", "successor": "H-E"},
            [("link", "SUPERSEDED_BY|Hypothesis:H-D|Hypothesis:H-E"), ("update", "Hypothesis:H-D")]),
           ("record_decision", {"decision": "DEC-1", "contract_version": "CV-1"}, [("link", "CHANGES|Decision:DEC-1|ContractVersion:CV-1")]),
           ("flag_orphan_component", {"component": "cmp-orphan"}, [("update", "Component:cmp-orphan")])]


@pytest.mark.parametrize("op,args,want", PROJ_OK)
def test_project_ops_commit_canonical_effects(proj, op, args, want):
    res, eff = proj.effects_of(lambda: proj.dep.direct(proj.token("researcher-1"), op, args, request_id="r1"))
    assert res.status == "OK", res
    assert sorted((e["kind"], e["ref"]) for e in eff) == sorted(want)
    assert all(e["kind"] != "external" for e in eff)


def test_project_evaluate_writes_machine_derived_verdict(proj):
    proj.dep.direct(proj.token("researcher-1"), "evaluate_hypothesis", {"hypothesis": "H-C"}, request_id="r1")
    v = proj.snap()["objects"]["Verdict:verdict-H-C-1"]["props"]
    assert v["value"] == "SUPPORTED" and proj.snap()["objects"]["Hypothesis:H-C"]["props"]["phase"] == "EVALUATED"


def test_project_via_tool_surface(proj):
    res, eff = proj.effects_of(lambda: proj.dep.call_tool(proj.token("agent-draft-1"), "create_hypothesis",
                                                          {"claim": "agent claim"}, request_id="r1"))
    assert res.status == "OK" and [e["kind"] for e in eff] == ["create"]


def test_reads(mfg, proj):
    t = mfg.token("planner-1")
    assert mfg.dep.read(t, "available_quantity", {"lot": "LOT-B-PX17"}).body["value"] == 140
    assert mfg.dep.read(t, "work_order_risk", {"work_order": "WO-42"}).body["value"]["at_risk"] is True
    assert mfg.dep.read(t, "get", {"type": "Warehouse", "key": "WH-A"}).status == "OK"
    assert mfg.dep.read(t, "no_such_read", {}).status == "UNKNOWN"
    assert mfg.dep.read("garbage", "available_quantity", {"lot": "LOT-B-PX17"}).status == "DENIED"
    assert proj.dep.read(proj.token("viewer-1"), "evidence_count", {"hypothesis": "H-C"}).body["value"] == 1
    assert proj.dep.read(proj.token("viewer-1"), "find_orphan_components", {}).body["value"] == ["cmp-orphan"]


def test_crash_then_restart_serves_again(mfg):
    mfg.dep.crash()
    assert mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", TR, request_id="r1").status == "UNAVAILABLE"
    mfg.dep.restart()
    assert mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", TR, request_id="r1").status == "OK"
