#!/usr/bin/env python3
"""`make rebuild-projections` — docs/experiment/spec/07_versioning_and_replay.md
"Projection rebuild": delete all hot projections and reconstruct them from
semantic/source history, then prove hash(rebuilt) == hash(before) over
deterministic fields.

Run directly:

    .venv/bin/python -m services.projection_builder.rebuild

Requires the stack to be up (`make up`) — connects to RDF4J and to
ontology_hot the same way tests/integration/ does (host-mapped ports via
.env), not the in-container SERVICE_DB_* convention services/
projection_builder/main.py uses.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.projection_builder.builder import build_all  # noqa: E402
from services.projection_builder.hashing import BUSINESS_COLUMNS, table_hash  # noqa: E402

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()


def table_hashes(conn: psycopg.Connection) -> dict[str, str]:
    hashes = {}
    with conn.cursor() as cur:
        for table, cols in BUSINESS_COLUMNS.items():
            cur.execute(f"SELECT {', '.join(cols)} FROM {table}")  # noqa: S608 - fixed internal column list, not user input
            col_names = [d.name for d in cur.description]
            rows = [dict(zip(col_names, row)) for row in cur.fetchall()]
            hashes[table] = table_hash(table, rows)
    return hashes


def main() -> int:
    db_env.load_dotenv()

    with psycopg.connect(db_env.ontology_hot_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()

        before = table_hashes(conn)

        client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
        try:
            stats = build_all(client, conn)
        finally:
            client.close()

        after = table_hashes(conn)

    print(f"rebuilt: work_order_risk={stats.work_order_risk_rows} "
          f"transfer_candidates={stats.transfer_candidates_rows} "
          f"current_inventory={stats.current_inventory_rows} "
          f"action_eligibility_summary={stats.action_eligibility_summary_rows}")
    all_match = True
    for table in BUSINESS_COLUMNS:
        match = before[table] == after[table]
        all_match = all_match and match
        print(f"{table}: before={before[table]} after={after[table]} {'MATCH' if match else 'MISMATCH'}")
    # docs/experiment/spec/13_repository_contract.md-style honesty: the CLI
    # itself surfaces a mismatch loudly rather than only via the pytest test
    # in tests/integration/test_projection_rebuild.py (which is the actual
    # pass/fail authority for this requirement).
    if not all_match:
        print("rebuild hash mismatch — see docs/experiment/spec/07_versioning_and_replay.md", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
