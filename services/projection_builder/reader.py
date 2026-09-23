"""Point-read helpers for ontology_hot's hot-projection tables — the "hot
read" side of H6 (docs/experiment/spec/01_hypotheses.md), used by
tests/integration/ and tests/performance/bench_phase4.py. A future Decision
API (Phase 5) is the eventual production caller; Phase 4 has no HTTP layer
of its own (docs/experiment/spec/04_architecture.md's "Decision API / MCP"
box sits ABOVE the hot-projection box in the component diagram) — reads
here are plain psycopg SELECTs, same as any other service's db_ops module.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from services.projection_builder.freshness import evaluate as evaluate_freshness


def get_work_order_risk(conn: psycopg.Connection, work_order_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM work_order_risk WHERE work_order_id = %s", (work_order_id,))
        row = cur.fetchone()
    if row is not None:
        row["freshness_status"] = evaluate_freshness(row["as_of"])
    return row


def get_current_inventory(conn: psycopg.Connection, part: str, warehouse: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM current_inventory WHERE part = %s AND warehouse = %s", (part, warehouse)
        )
        row = cur.fetchone()
    if row is not None:
        row["freshness_status"] = evaluate_freshness(row["as_of"])
    return row


def get_transfer_candidates(conn: psycopg.Connection, work_order_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM transfer_candidates WHERE work_order_id = %s ORDER BY candidate_id",
            (work_order_id,),
        )
        rows = cur.fetchall()
    for row in rows:
        row["freshness_status"] = evaluate_freshness(row["as_of"])
    return rows


def get_action_eligibility_summary(conn: psycopg.Connection, work_order_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM action_eligibility_summary WHERE work_order_id = %s", (work_order_id,)
        )
        row = cur.fetchone()
    if row is not None:
        row["freshness_status"] = evaluate_freshness(row["as_of"])
    return row
