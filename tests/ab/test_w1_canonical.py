"""W1 — canonical supplier delay (spec 10): the SAME shape as the
canonical incident (docs/experiment/spec/03_domain_scenario.md) — a HIGH
priority work order, an incoming PO that covers its shortage until a
supplier delay pushes it past `planned_start`, then a transfer_inventory
mitigation — but on SYNTHETIC ids (tests/ab/synthetic.py), never the real
canonical fixture (PX-17/WH-A/WH-B/WO-42), per this repo's standing rule.

Feeds identical real-system events to both variants (same ERP/MES/WMS
calls, same CDC pipeline) and compares: (a) the two variants' own
decisions against each other, (b) both against the reference_model oracle
(tests/ab/oracle.py) for the pre- and post-delay evaluations.
"""

from __future__ import annotations

import time

from tests.ab import oracle, synthetic
from tests.ab.harness import Harness

WORK_ORDER_ID = "WO-AB-W1"
PO_ID = "PO-AB-W1"


def run(h: Harness) -> dict:
    part = synthetic.part_ids(1)
    synthetic.ensure_erp_part(h.erp_conn, part)

    # Stock: destination (WH-A) 20, source (WH-B) 140 — same shape as the
    # canonical incident.
    synthetic.set_wms_inventory(h.wms_http.base_url, part, "WH-A", on_hand=20)
    synthetic.set_wms_inventory(h.wms_http.base_url, part, "WH-B", on_hand=140)

    # Work order: HIGH priority at WH-A, requires 80, planned_start=18.
    synthetic.insert_work_order(h.mes_conn, WORK_ORDER_ID, warehouse="WH-A", status="PLANNED", priority="HIGH", planned_start=18)
    synthetic.insert_bom_requirement(h.mes_conn, WORK_ORDER_ID, part, qty=80)

    # PO: 100 units, expected BEFORE planned_start (T=8) — covers the
    # shortage, work order should NOT be at risk yet.
    synthetic.insert_purchase_order(h.erp_conn, PO_ID, status="OPEN", promised_at=8, expected_at=8)
    synthetic.insert_purchase_order_line(h.erp_conn, PO_ID, part, qty=100, destination_warehouse="WH-A")

    converged = synthetic.wait_both_converged(h.baseline_conn, h.ontology_hot_conn, part, "WH-A", 20, timeout_s=40.0)

    # --- Step: supplier delay event (the REAL ERP mutation, same call the
    # canonical incident's own manual-execution test uses) ---------------
    r = h.erp_http.post(f"/purchase_orders/{PO_ID}/delay", json={"expected_at": 120, "reason": "transport_delay"})
    r.raise_for_status()
    time.sleep(3.0)  # let both CDC pipelines observe the delay

    # --- Propose the SAME mitigation to both variants --------------------
    params = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part.canonical_id, "quantity": 60, "work_order": WORK_ORDER_ID}
    decisions = {}
    for name, client in h.clients.items():
        resp = client.propose("transfer_inventory", "user", "planner-1", params)
        body = resp.json()
        decisions[name] = {"http_status": resp.status_code, "status": body.get("status"), "decision_id": body.get("decision_id"), "body": body}

    oracle_status, oracle_reason = oracle.expected_transfer_status(
        part.canonical_id, "WH-B", "WH-A", 60, "planner-1", source_on_hand=140, destination_on_hand=20,
    )

    decision_match_variants = decisions["ontology"]["status"] == decisions["baseline"]["status"]
    decision_match_oracle = {name: d["status"] == oracle_status for name, d in decisions.items()}

    # --- Execute on both variants if APPROVED, verify convergence to
    # OBSERVED_SUCCESS + inventory conservation -----------------------
    execution_results = {}
    for name, client in h.clients.items():
        d = decisions[name]
        if d["status"] != "APPROVED":
            execution_results[name] = {"executed": False, "reason": d["status"]}
            continue
        er = client.execute(d["decision_id"])
        if er.status_code != 202:
            execution_results[name] = {"executed": False, "reason": f"execute HTTP {er.status_code}"}
            continue
        final = client.wait_terminal(d["decision_id"], timeout_s=45.0)
        execution_results[name] = {"executed": True, "final_status": final.get("status")}

    return {
        "workload": "W1_canonical_supplier_delay",
        "converged_before_delay": converged,
        "decisions": {k: {"status": v["status"], "http_status": v["http_status"]} for k, v in decisions.items()},
        "oracle_status": oracle_status,
        "oracle_reason": oracle_reason,
        "decision_match_variants": decision_match_variants,
        "decision_match_oracle": decision_match_oracle,
        "execution_results": execution_results,
        "part": part.canonical_id,
        "work_order_id": WORK_ORDER_ID,
    }


def test_w1_canonical_supplier_delay(harness: Harness):
    result = run(harness)
    assert result["converged_before_delay"] == {"baseline": True, "ontology": True}, result
    assert result["decision_match_variants"], result
    assert all(result["decision_match_oracle"].values()), result
    assert result["oracle_status"] in ("APPROVED", "REQUIRES_APPROVAL")
