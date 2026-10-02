"""Manufacturing logic vs its v1 sources (differential), and the two actions the frozen IR cannot authorize."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from domains._pack import load_ir
from domains.manufacturing.logic import data
from mfg_helpers import NOW, Snap, failed_gates, gate, make

V1 = Path(__file__).resolve().parents[3]  # operational-ontology-poc (the v1 POC repo root)


def _load_by_path(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, V1 / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_constants_match_v1_sources():
    d = json.loads((V1 / "contracts/policies/v2/data.json").read_text())
    assert d["default_safety_stock_v2"] == data.DEFAULT_SAFETY_STOCK_V2
    assert {(p, w): v for p, ws in d["safety_stock_v2"].items() for w, v in ws.items()} == data.SAFETY_STOCK_V2
    t = (V1 / "contracts/actions/v3/transfer_inventory.yaml").read_text()
    assert int(re.search(r"approval_threshold_units:\s*(\d+)", t).group(1)) == data.APPROVAL_THRESHOLD_UNITS
    assert int(re.search(r"max_evidence_freshness_s:\s*(\d+)", t).group(1)) == data.MAX_EVIDENCE_FRESHNESS_S
    x = (V1 / "contracts/actions/v1/expedite_purchase_order.yaml").read_text()
    assert int(re.search(r"approval_threshold_cost:\s*(\d+)", x).group(1)) == data.APPROVAL_THRESHOLD_COST


def test_risk_matches_reference_model_on_seed_and_after_delay_recovery():
    if str(V1) not in sys.path:
        sys.path.append(str(V1))  # appended: never shadows round2 modules
    import reference_model.derive as derive
    import reference_model.state as ref
    e, _, _ = make()
    w = ref.empty_state({}, {}, ref.PolicyConfig())
    lots = {("PX-17", "WH-A"): 20, ("PX-17", "WH-B"): 140}
    inv = {k: ref.InventoryLot(f"L{i}", k[0], k[1], v, 0, "OK", 0) for i, (k, v) in enumerate(lots.items())}
    wos = {"WO-42": ref.WorkOrder("WO-42", "PLANNED", "HIGH", 18, "WH-A", {"PX-17": 80}),
           "WO-43": ref.WorkOrder("WO-43", "RUNNING", "LOW", 30, "WH-B", {"PX-900": 5})}
    pos = {"PO-991": ref.PurchaseOrder("PO-991", "PX-17", 100, "WH-A", 120, "DELAYED")}
    inv[("PX-900", "WH-B")] = ref.InventoryLot("L9", "PX-900", "WH-B", 10, 0, "OK", 0)
    w = replace(w, inventory=inv, work_orders=wos, purchase_orders=pos)
    for wo in ("WO-42", "WO-43"):
        want = derive.work_order_risk(w, wo)
        got = e.call_function("work_order_risk", {"work_order": wo})
        assert (got["shortage"], got["at_risk"]) == (want.shortage, want.at_risk)
    assert want.at_risk is False and derive.work_order_risk(w, "WO-42").shortage == 60  # known-positive and known-negative


def test_decision_content_hash_equals_v1_hashing_module():
    h = _load_by_path("v1_hashing", "services/decision_service/hashing.py")
    e, _, _ = make()
    want = h.decision_content_hash("human", "planner-1", None, "ES-1", "v3", "v3", "v2", "v2", "transfer_inventory", 3,
                                   {"quantity": 100, "part": "PX-900"})
    assert e.call_function("decision_content_hash", {"decision": "D-1"}) == want
    assert want != h.decision_content_hash("human", "planner-1", None, "ES-1", "v3", "v3", "v2", "v2", "transfer_inventory", 3,
                                           {"quantity": 101, "part": "PX-900"})


def test_resolve_canonical_id_maps_and_passes_through():
    e, _, _ = make()
    assert e.call_function("resolve_canonical_id", {"source_local_id": "SKU-88429"}) == "PX-17"
    assert e.call_function("resolve_canonical_id", {"source_local_id": "PX-900"}) == "PX-900"


def test_recommend_transfer_for_at_risk_work_order_and_none_otherwise():
    e, _, _ = make()
    rec = e.call_function("recommend_transfer_for_work_order", {"work_order": "WO-42"})
    assert dict(rec["parameters"]) == {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17",
                                       "quantity": 60, "work_order": "WO-42"}
    assert e.call_function("recommend_transfer_for_work_order", {"work_order": "WO-43"}) is None


@pytest.mark.parametrize("who", ["planner-1", "junior-1", "supervisor-1", "senior-1", "agent-1"])
def test_expedite_and_reschedule_cannot_pass_authority_on_the_frozen_ir(who):
    """FINDING: their authority_refs name rules whose capability is action:transfer_inventory, so no allow rule
    matches capability action:expedite_purchase_order / action:reschedule_work_order, and their relation selectors
    (Warehouse#...) have no Warehouse input to bind. A principal_selector binding cannot help (never consulted)."""
    e, wms, _ = make()
    z = Snap(e, wms)
    for action, inputs in (("expedite_purchase_order", {"po_id": "PO-992", "expedite_fee": 100}),
                           ("reschedule_work_order", {"work_order_id": "WO-43", "new_planned_start": 50})):
        rec = e.propose(action, inputs, who, idempotency_key=f"{action}-{who}")
        assert rec["state"] == "DENIED" and failed_gates(rec) == ["authority"]
        assert gate(rec, "authority")["detail"]["allow"] == []
    assert z.unchanged()


def _patched_ir() -> dict:
    """TEST-ONLY variant of the IR: per-action allow rules with the right capability and a role selector."""
    ir = copy.deepcopy(load_ir("manufacturing"))
    for action in ("expedite_purchase_order", "reschedule_work_order"):
        rid = f"patched-{action}"
        ir["authority_rules"].append({"id": rid, "principal_selector": "role:planner", "capability": f"action:{action}",
                                      "resource_selector": "*", "effect": "allow", "delegation_allowed": False})
        for a in ir["actions"]:
            if a["id"] == action:
                a["authority_refs"] = [f"auth:{rid}"]
    return ir


def test_expedite_and_reschedule_logic_works_once_the_ir_authorizes_them():
    e, wms, pack = make(package=_patched_ir())
    erp, mes = pack[1][("external_call", "ERP")], pack[1][("external_call", "MES")]
    ok = e.propose("expedite_purchase_order", {"po_id": "PO-992", "expedite_fee": 100}, "planner-1", idempotency_key="e1")
    assert ok["state"] == "RECONCILED_SUCCESS" and erp.calls[0]["payload"] == {"expedite_fee": 100, "$key": "PO-992"}
    pend = e.propose("expedite_purchase_order", {"po_id": "PO-992", "expedite_fee": 900}, "planner-1", idempotency_key="e2")
    assert pend["state"] == "PENDING_APPROVAL"  # over approval_threshold_cost; no approval rule matches -> nobody approves
    z = Snap(e, wms)
    for bad in ({"po_id": "PO-992", "expedite_fee": -1}, ):
        r = e.propose("expedite_purchase_order", bad, "planner-1", idempotency_key="e3")
        assert r["state"] == "DENIED" and failed_gates(r) == ["preconditions"]
    assert z.unchanged() and len(erp.calls) == 1
    r = e.propose("reschedule_work_order", {"work_order_id": "WO-43", "new_planned_start": 55}, "planner-1", idempotency_key="r1")
    assert r["state"] == "RECONCILED_SUCCESS" and mes.calls[0]["payload"]["new_planned_start"] == 55
    hi = e.propose("reschedule_work_order", {"work_order_id": "WO-42", "new_planned_start": 55}, "planner-1", idempotency_key="r2")
    assert hi["state"] == "PENDING_APPROVAL"  # HIGH priority needs approval
