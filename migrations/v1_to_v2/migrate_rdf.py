#!/usr/bin/env python3
"""V1 -> V2 RDF4J migration (docs/experiment/spec/07_versioning_and_replay.md
"Migrations in migrations/v1_to_v2 ... migrate CURRENT state in RDF4J and
projections; historical decisions and snapshots are never rewritten").

Deletes every live `fac:availableQuantity` triple from the CURRENT observed
graph only (services/common/rdf_graphs.py::OBSERVED_GRAPH) — the property
retired by contracts/ontology/v2/fac-core.ttl. Never touches:
  - any per-decision named graph (services/common/rdf_graphs.py::decision_graph_iri) —
    a Decision's own EvidenceSnapshot facts_used JSON is a frozen COPY of
    what was observed at proposal time, not a live reference, so this
    migration cannot and must not reach into it;
  - the ontology/SHACL-shapes graphs — those are separate contract
    artifacts (contracts/ontology/v2/, contracts/shapes/v2/), not data.

Idempotent: a SPARQL DELETE WHERE over a pattern that no longer matches
anything is a no-op, so running this twice is safe.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.common.rdf_graphs import OBSERVED_GRAPH  # noqa: E402

DELETE_AVAILABLE_QUANTITY = f"""
PREFIX fac: <https://example.local/factory/>
DELETE {{ GRAPH <{OBSERVED_GRAPH}> {{ ?lot fac:availableQuantity ?available . }} }}
WHERE  {{ GRAPH <{OBSERVED_GRAPH}> {{ ?lot fac:availableQuantity ?available . }} }}
"""


def migrate(client: RDF4JClient) -> int:
    """Returns the number of fac:InventoryLot rows that HAD the triple
    before this ran (measured by a COUNT query before the delete, since
    RDF4J's SPARQL Update response carries no affected-row count)."""
    count_query = f"""
    PREFIX fac: <https://example.local/factory/>
    SELECT (COUNT(*) AS ?n) WHERE {{
      GRAPH <{OBSERVED_GRAPH}> {{ ?lot fac:availableQuantity ?available . }}
    }}
    """
    before = client.select(count_query)
    n = int(before[0]["n"]) if before else 0

    resp = client.update(DELETE_AVAILABLE_QUANTITY)
    if resp.status_code not in (200, 204):
        raise RuntimeError(f"v1_to_v2 RDF migration DELETE failed: HTTP {resp.status_code}: {resp.text[:500]}")
    return n


def main() -> int:
    db_env.load_dotenv()
    client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    try:
        n = migrate(client)
    finally:
        client.close()
    print(f"[migrate_rdf v1_to_v2] deleted fac:availableQuantity from {n} InventoryLot row(s) in the observed graph")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
