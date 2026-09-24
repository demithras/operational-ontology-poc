"""W6 (Phase 8 A/B experiment, docs/experiment/spec/10_ab_experiment.md):
a NOVEL cross-system relation this repo never queried before Phase 8 —
"for a given at-risk work order, which supplier(s) does its shortage
ultimately trace back to" — crossing MES (BomRequirement/WorkOrder) into
ERP (PurchaseOrderLine/PurchaseOrder/Supplier) via WMS's own warehouse id
as the join key. Every triple this SPARQL query traverses was ALREADY
mapped into RDF since Phase 3 (services/ingestion/mapping.py:
fac:requiresPart, fac:workOrder, fac:destinationWarehouse, fac:purchaseOrder,
fac:suppliedBy) — this is a genuinely NEW QUERY over EXISTING data, no
ingestion/mapping/ontology change required. See
services/baseline/forensics.py for the relational equivalent, and
docs/experiment/implementation-notes.md Phase 8 item 2 (W6) for the
measured effort comparison.
"""

from __future__ import annotations

from services.common.sparql_escape import escape_sparql_literal

FAC_PREFIX = "PREFIX fac: <https://example.local/factory/>"


def at_risk_suppliers(rdf4j_client, work_order_id: str) -> list[dict]:
    safe_wo = escape_sparql_literal(work_order_id)
    query = f"""
{FAC_PREFIX}
SELECT DISTINCT ?supplierId ?poId ?partUri WHERE {{
  GRAPH <https://example.local/oo/graph/observed> {{
    ?wo a fac:WorkOrder ; fac:workOrderId "{safe_wo}" ; fac:warehouse ?whUri .
    ?req a fac:BomRequirement ; fac:workOrder ?wo ; fac:requiresPart ?partUri .
    ?line a fac:PurchaseOrderLine ; fac:part ?partUri ; fac:destinationWarehouse ?whUri ; fac:purchaseOrder ?po .
    ?po fac:status ?status ; fac:suppliedBy ?supplier .
    FILTER(?status != "RECEIVED" && ?status != "CANCELLED")
    ?supplier fac:supplierId ?supplierId .
    ?po fac:poId ?poId .
  }}
}}
"""
    rows = rdf4j_client.select(query)
    return [{"supplier_id": r["supplierId"], "po_id": r["poId"], "part": r["partUri"].rsplit("/", 1)[-1]} for r in rows]
