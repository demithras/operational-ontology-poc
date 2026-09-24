"""One-shot lookup of the CDC-observed fac:WmsTransferRecord for a given
action_execution_id (contracts/ontology/v1/fac-core.ttl,
services/ingestion/mapping.py) — shared by services/action_worker/activities.py
(which polls this in a loop with Temporal heartbeats while WAITING for the
observation) and services/reconciliation (which calls it ONCE per poll
cycle as its own independent re-check, H12). One query, two callers, so the
"what counts as a correlated WMS transfer record" definition can never
drift between the executing side and the verifying side.
"""

from __future__ import annotations

from services.common.sparql_escape import escape_sparql_literal

FAC_PREFIX = "PREFIX fac: <https://example.local/factory/>"


def fetch_wms_transfer_record(rdf4j_client, action_execution_id: str) -> dict | None:
    safe_id = escape_sparql_literal(action_execution_id)
    query = f"""
{FAC_PREFIX}
SELECT ?status ?requestedQuantity ?actualQuantity WHERE {{
  GRAPH <https://example.local/oo/graph/observed> {{
    ?tr a fac:WmsTransferRecord ; fac:actionExecutionId "{safe_id}" ;
        fac:transferStatus ?status ; fac:requestedQuantity ?requestedQuantity ; fac:actualQuantity ?actualQuantity .
  }}
}}
"""
    rows = rdf4j_client.select(query)
    if not rows:
        return None
    r = rows[0]
    return {"status": r["status"], "requested_quantity": int(r["requestedQuantity"]), "actual_quantity": int(r["actualQuantity"])}
