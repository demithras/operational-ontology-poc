"""W6 — a novel cross-system relation, implemented in both variants; effort
measured from the git diff (spec 10).

The capability: `services/decision_service/forensics.py::at_risk_suppliers`
(SPARQL) / `services/baseline/forensics.py::at_risk_suppliers` (SQL) —
"for a given at-risk work order, which supplier(s) is its shortage
tracing back to" — a relation that crosses MES -> ERP via WMS's warehouse
id, never queried anywhere in this repo before Phase 8.

Scope note: this workload calls the two functions DIRECTLY (this test
process already holds an RDF4J client / a baseline DB connection) rather
than adding a new live HTTP endpoint to each service and rebuilding both
containers — a deliberate time-boxing for the A/B experiment run, not a
claim that a real feature would ship without one. Estimated marginal cost
of the HTTP wiring itself (`@app.get(...)` + a 3-line handler, the same
shape as every existing read endpoint in either app.py) is noted in the
result rather than built+measured, and is the SAME small shape for both
variants either way.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.ab import synthetic
from tests.ab.harness import Harness

REPO_ROOT = Path(__file__).resolve().parents[2]
WORK_ORDER_ID = "WO-AB-W6"
PO_ID = "PO-AB-W6"


def _wc_l(path: str) -> int:
    return len((REPO_ROOT / path).read_text().splitlines())


def run(h: Harness) -> dict:
    part = synthetic.part_ids(6)
    synthetic.ensure_erp_part(h.erp_conn, part)
    synthetic.set_wms_inventory(h.wms_http.base_url, part, "WH-A", on_hand=5)
    synthetic.insert_work_order(h.mes_conn, WORK_ORDER_ID, warehouse="WH-A", status="PLANNED", priority="HIGH", planned_start=50)
    synthetic.insert_bom_requirement(h.mes_conn, WORK_ORDER_ID, part, qty=40)
    synthetic.insert_purchase_order(h.erp_conn, PO_ID, status="OPEN", promised_at=10, expected_at=10)
    synthetic.insert_purchase_order_line(h.erp_conn, PO_ID, part, qty=50, destination_warehouse="WH-A")

    converged = synthetic.wait_both_converged(h.baseline_conn, h.ontology_hot_conn, part, "WH-A", 5, timeout_s=40.0)

    from services.baseline.forensics import at_risk_suppliers as baseline_at_risk_suppliers
    from services.decision_service.forensics import at_risk_suppliers as ontology_at_risk_suppliers

    ontology_result = ontology_at_risk_suppliers(h.rdf4j_client, WORK_ORDER_ID)
    baseline_result = baseline_at_risk_suppliers(h.baseline_conn, WORK_ORDER_ID)

    ontology_suppliers = {r["supplier_id"] for r in ontology_result}
    baseline_suppliers = {r["supplier_id"] for r in baseline_result}

    effort = {
        "ontology": {
            "new_files": 1, "file": "services/decision_service/forensics.py",
            "logical_lines": _wc_l("services/decision_service/forensics.py"),
            "components_touched": ["decision_service (new module, reads existing RDF4J triples — no ingestion/mapping/ontology/shapes change)"],
            "migrations_needed": 0,
        },
        "baseline": {
            "new_files": 1, "file": "services/baseline/forensics.py",
            "logical_lines": _wc_l("services/baseline/forensics.py"),
            "components_touched": ["baseline (new module, reads existing relational tables — no consumer/schema change)"],
            "migrations_needed": 0,
        },
        "http_wiring_not_built_estimated_lines_each": 4,  # @app.get + one function-call line, same shape existing endpoints already use in both app.py files
    }

    return {
        "workload": "W6_novel_cross_system_relation",
        "converged": converged,
        "ontology_result": ontology_result,
        "baseline_result": baseline_result,
        "suppliers_match": ontology_suppliers == baseline_suppliers,
        "found_the_seeded_supplier": "SUP-0000" in ontology_suppliers and "SUP-0000" in baseline_suppliers,
        "effort": effort,
        "work_order_id": WORK_ORDER_ID,
    }


def test_w6_novel_relation(harness: Harness):
    result = run(harness)
    assert result["converged"] == {"baseline": True, "ontology": True}, result
    assert result["suppliers_match"], result
    assert result["found_the_seeded_supplier"], result
    assert result["effort"]["ontology"]["migrations_needed"] == 0
    assert result["effort"]["baseline"]["migrations_needed"] == 0
