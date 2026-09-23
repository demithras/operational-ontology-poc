"""Phase 4 item 3 (docs/experiment/briefs/phase4.md) /
docs/experiment/spec/07_versioning_and_replay.md "Projection rebuild":
truncate + reconstruct all four hot-projection tables from the semantic
core, and assert hash(rebuilt) == hash(before) over deterministic business
fields. Also the pass/fail authority for `make rebuild-projections`
(services/projection_builder/rebuild.py`'s own printed MATCH/MISMATCH is a
human-readable echo of this same check, not a second implementation of it).

Reuses services.projection_builder.builder.build_all directly (the exact
same function the live poll loop and rebuild.py both call) rather than
shelling out to `make rebuild-projections`.

IMPORTANT: build_all() is called on a DEDICATED, non-autocommit connection
here, never on the shared `ontology_hot_conn` fixture (which is autocommit,
for read-polling convenience elsewhere in tests/integration/). The live
services/projection_builder container's poll loop is ALSO continuously
calling build_all() against this same database every few seconds
(OO_PROJECTION_POLL_INTERVAL_S) on its own properly-transactional pooled
connection. Two concurrent full TRUNCATE+INSERT rebuilds are only safe
against each other when BOTH run inside one transaction each — TRUNCATE's
ACCESS EXCLUSIVE lock then serializes them (the second blocks until the
first commits) instead of interleaving. Under autocommit, each statement is
its own transaction, so the live poller's TRUNCATE can land in between two
of THIS test's individual INSERT statements, producing a spurious
`UniqueViolation` on a (part, warehouse)/etc. row that both writers computed
independently — caught empirically during Phase 4 implementation (see
docs/experiment/implementation-notes.md).
"""

from __future__ import annotations

import psycopg

from seed import db_env
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


def test_rebuild_reproduces_identical_business_state(ontology_hot_conn, rdf4j_client: RDF4JClient):
    write_conn = psycopg.connect(db_env.ontology_hot_dsn(), connect_timeout=3)  # autocommit=False (default)
    try:
        # Ensure at least one build has happened (fresh ontology_hot
        # databases have empty tables, which still hash deterministically,
        # but a build exercises the real path end to end rather than
        # comparing two empty sets).
        build_all(rdf4j_client, write_conn)

        before = _table_hashes(ontology_hot_conn)

        stats = build_all(rdf4j_client, write_conn)
        assert stats.work_order_risk_rows >= 0  # sanity: build_all ran without raising

        after = _table_hashes(ontology_hot_conn)
    finally:
        write_conn.close()

    for table in BUSINESS_COLUMNS:
        assert after[table] == before[table], f"{table}: rebuild hash mismatch (semantic core is unchanged)"
