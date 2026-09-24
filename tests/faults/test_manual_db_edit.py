"""F37 (docs/experiment/spec/09_failure_and_adversarial_matrix.md "source DB
direct manual edit -> WMS -> observed as external fact with provenance, not
retroactively attributed to any action").

Connects DIRECTLY to WMS's own Postgres database (bypassing the WMS HTTP
API entirely — no `/transfers` call, no `action_execution_id`, no test-mode
fault registry) and UPDATEs an inventory_lots row by raw SQL, simulating an
operator/DBA hand-editing the source system out of band. This is a
DIFFERENT fault from F36: F36 is a concurrent GOVERNED-adjacent WMS-API
write (still creates observable WMS facts the normal way); F37 has no
WMS-API-level event at all — the row simply changes.

The change still flows through the real CDC pipeline (Debezium reads
Postgres's WAL directly — it has no concept of "via the API" vs. "via
psql") and becomes an observed fact WITH provenance (services/ingestion's
own oo:Observation record, sourceSystem="wms", sourceTable="inventory_lots"
— the SAME provenance every CDC-observed fact gets, phase3.md item 5).
What must NOT happen: this manual edit must never be attributed to any
oo:ActionExecution/Decision — there is structurally nothing to attribute it
to, since `transfers` (the ONLY table an ActionExecution's effect is
ever correlated through, services/action_worker/outcome_eval.py) was never
touched at all.
"""

from __future__ import annotations

import httpx
import psycopg

from seed import db_env
from services.projection_builder import reader
from tests.integration.conftest import wait_until
from tests.integration.decision_helpers import set_inventory_and_wait


def test_f37_direct_manual_db_edit_observed_with_provenance_not_attributed_to_any_action(
    wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, rdf4j_client
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910902", "WH-C", on_hand=50)

    lot_row = wms_client.get("/inventory_lots", params={"part": "SKU-910902", "warehouse_id": "WH-C"}).json()[0]
    lot_id = lot_row["lot_id"]

    # A raw, out-of-band UPDATE — no WMS API call, no action_execution_id,
    # nothing the governance layer ever proposed or approved.
    with psycopg.connect(db_env.wms_dsn(), autocommit=True) as wms_conn:
        with wms_conn.cursor() as cur:
            cur.execute(
                "UPDATE inventory_lots SET on_hand = on_hand + 17, version = version + 1, updated_at = now() WHERE lot_id = %s",
                (lot_id,),
            )
            assert cur.rowcount == 1

    # 1. Observed as an external fact WITH provenance — the hot projection
    # (real CDC + identity resolution + projection-builder round trip)
    # reflects the new value, exactly like any other WMS write.
    def _bumped() -> dict | None:
        current = reader.get_current_inventory(ontology_hot_conn, part, "WH-C")
        return current if current is not None and current["on_hand"] == 67 else None

    row = wait_until(_bumped)
    assert row is not None, "current_inventory never converged to on_hand=67 (50 + 17) after the manual edit"

    obs_rows = rdf4j_client.select(
        f"""
        SELECT ?applied WHERE {{
          GRAPH <https://example.local/oo/graph/provenance> {{
            ?obs a <https://example.local/oo/Observation> ;
                 <https://example.local/oo/sourceSystem> "wms" ;
                 <https://example.local/oo/sourceTable> "inventory_lots" ;
                 <https://example.local/oo/sourcePk> "{lot_id}" ;
                 <https://example.local/oo/applied> ?applied .
          }}
        }}
        """
    )
    assert any(r["applied"] == "true" for r in obs_rows), "the manual edit must still produce a real, applied Observation record"

    # 2. NEVER retroactively attributed to any action. Structurally
    # unattributable: no `transfers` row exists for this change at all (the
    # ONLY table an ActionExecution's effect is ever correlated through —
    # services/action_worker/outcome_eval.py), so there is nothing an
    # action_execution_id could even correlate against. Confirmed two ways:
    # (a) no WMS transfer touches this lot's part/warehouse with a matching
    #     +17 delta;
    # (b) no oo:ActionExecution/oo:Outcome resource references this lot at
    #     all — this InventoryLot's only RDF provenance is the plain
    #     fac:InventoryLot Observation checked above, never an
    #     oo:ActionExecution link.
    # Scoped to THIS exact part (not just the warehouse) so a concurrent,
    # genuinely governed transfer touching WH-C for a DIFFERENT part can
    # never make this assertion a false failure.
    transfers_touching_lot = rdf4j_client.select(
        f"""
        PREFIX fac: <https://example.local/factory/>
        SELECT ?tr WHERE {{
          GRAPH <https://example.local/oo/graph/observed> {{
            ?tr a fac:WmsTransferRecord ;
                fac:destinationWarehouse ?wh ;
                fac:part <https://example.local/factory/instance/Part/{part}> .
            ?wh fac:warehouseId "WH-C" .
          }}
        }}
        """
    )
    assert transfers_touching_lot == [], "a manual DB edit must never show up as a WmsTransferRecord"
