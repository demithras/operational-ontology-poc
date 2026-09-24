#!/usr/bin/env python3
"""`make deploy-v2` — the V1 -> V2 contract redeploy, end to end
(docs/experiment/spec/07_versioning_and_replay.md).

Order matters:
  1. migrate_rdf.py — delete the retired fac:availableQuantity triples from
     the CURRENT observed graph (never touches historical decision graphs).
  2. Flip contracts/manifests/deployed_version.json's ontology/shapes/
     actions/policies/projections pointers to "v2" — services/decision_service
     (propose()), services/projection_builder (its next poll cycle), and
     OPA (already watching the whole contracts/policies/ tree) all pick
     this up live, no restart required (see those modules' own Phase 7
     docstrings for why).
  3. Force an IMMEDIATE projection rebuild under the new v2 projection
     definition (services/projection_builder/rebuild.py's own table_hashes
     before/after proof) rather than waiting for the next ~3s poll cycle —
     this is also this migration's own "projection rebuild after
     migration" proof point (docs/experiment/spec/07_versioning_and_replay.md
     "Projection rebuild").

Never touches any already-committed Decision, EvidenceSnapshot, or other
historical RDF — those are immutable by construction elsewhere in this
codebase (services/decision_service/rdf_writer.py never re-POSTs into an
existing decision graph).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from migrations.v1_to_v2.migrate_rdf import migrate as migrate_rdf  # noqa: E402
from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.projection_builder.builder import build_all  # noqa: E402
from services.projection_builder.hashing import BUSINESS_COLUMNS, table_hash  # noqa: E402

DEPLOYED_VERSION_PATH = REPO_ROOT / "contracts" / "manifests" / "deployed_version.json"

V2_KINDS = ("ontology", "shapes", "actions", "policies", "projections")


def _table_hashes(conn: psycopg.Connection) -> dict[str, str]:
    hashes = {}
    with conn.cursor() as cur:
        for table, cols in BUSINESS_COLUMNS.items():
            cur.execute(f"SELECT {', '.join(cols)} FROM {table}")  # noqa: S608 - fixed internal column list
            col_names = [d.name for d in cur.description]
            rows = [dict(zip(col_names, row)) for row in cur.fetchall()]
            hashes[table] = table_hash(table, rows)
    return hashes


def deploy() -> dict:
    db_env.load_dotenv()

    rdf_client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    try:
        migrated_lot_count = migrate_rdf(rdf_client)
    finally:
        rdf_client.close()

    current = json.loads(DEPLOYED_VERSION_PATH.read_text())
    before_version = dict(current)
    for kind in V2_KINDS:
        current[kind] = "v2"
    DEPLOYED_VERSION_PATH.write_text(json.dumps(current, indent=2, sort_keys=False) + "\n")

    with psycopg.connect(db_env.ontology_hot_dsn()) as conn:
        before = _table_hashes(conn)
        rdf_client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
        try:
            stats = build_all(rdf_client, conn)
        finally:
            rdf_client.close()
        after = _table_hashes(conn)

    rebuild_matches = {table: (before[table] == after[table]) for table in BUSINESS_COLUMNS}

    return {
        "migrated_availableQuantity_rows": migrated_lot_count,
        "deployed_version_before": before_version,
        "deployed_version_after": current,
        "rebuild_stats": {
            "work_order_risk": stats.work_order_risk_rows,
            "transfer_candidates": stats.transfer_candidates_rows,
            "current_inventory": stats.current_inventory_rows,
            "action_eligibility_summary": stats.action_eligibility_summary_rows,
        },
        "rebuild_hash_matches": rebuild_matches,
    }


def main() -> int:
    result = deploy()
    print(json.dumps(result, indent=2, sort_keys=True))
    if not all(result["rebuild_hash_matches"].values()):
        print(
            "v1_to_v2 deploy: projection rebuild hash MISMATCH after migration — see "
            "docs/experiment/spec/07_versioning_and_replay.md 'Projection rebuild'",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
