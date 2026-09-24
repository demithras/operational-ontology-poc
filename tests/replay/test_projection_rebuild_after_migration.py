"""docs/experiment/spec/07_versioning_and_replay.md "Projection rebuild"
item — explicitly AFTER a migration has run (not just the generic Phase 4
mechanism tests/integration/test_projection_rebuild.py already proves,
which happens to run under whatever version is live but never asserts
that a migration actually took place first).

Reuses the EXACT SAME build_all()/table_hash() mechanism as the Phase 4
test and migrations/v1_to_v2/deploy.py's own inline proof — this is not a
second implementation, it is the explicit "and it still holds true
post-migration" assertion the brief calls for.
"""

from __future__ import annotations

import psycopg
import pytest

from seed import db_env
from services.common.contract_versions import deployed_version
from services.common.rdf4j_client import RDF4JClient
from services.projection_builder.builder import build_all
from services.projection_builder.hashing import BUSINESS_COLUMNS, table_hash


def _table_hashes(conn) -> dict[str, str]:
    hashes = {}
    with conn.cursor() as cur:
        for table, cols in BUSINESS_COLUMNS.items():
            cur.execute(f"SELECT {', '.join(cols)} FROM {table}")  # noqa: S608 - fixed internal column list
            col_names = [d.name for d in cur.description]
            rows = [dict(zip(col_names, row)) for row in cur.fetchall()]
            hashes[table] = table_hash(table, rows)
    return hashes


def test_projection_rebuild_matches_after_v1_to_v2_migration(rdf4j_reachable, ontology_hot_conn):
    live = deployed_version()
    if live["projections"] == "v1":
        pytest.skip(
            "deployed_version.json 'projections' is still v1 — run `make deploy-v2` "
            "(migrations/v1_to_v2/deploy.py) first, per docs/experiment/implementation-notes.md Phase 7 section"
        )
    if not rdf4j_reachable:
        pytest.skip("RDF4J not reachable")

    db_env.load_dotenv()
    conn = psycopg.connect(db_env.ontology_hot_dsn())
    client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    try:
        before = _table_hashes(conn)
        build_all(client, conn)
        conn.commit()
        after = _table_hashes(conn)
    finally:
        client.close()
        conn.close()

    mismatches = {t: (before[t], after[t]) for t in BUSINESS_COLUMNS if before[t] != after[t]}
    assert not mismatches, (
        f"projection rebuild under the migrated ('{live['projections']}') definitions produced a "
        f"different hash than before rebuilding: {mismatches}"
    )
