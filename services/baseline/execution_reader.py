"""Read-only lookups for baseline ActionExecution/Outcome rows — same role
as services/decision_service/execution_reader.py, plain SQL instead of
SPARQL."""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row


def get_execution(conn: psycopg.Connection, action_execution_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM action_executions WHERE action_execution_id = %s", (action_execution_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute("SELECT outcome_id FROM outcomes WHERE action_execution_id = %s", (action_execution_id,))
        outcome = cur.fetchone()
    if outcome:
        row["outcome_id"] = outcome["outcome_id"]
    return row


def get_outcome(conn: psycopg.Connection, outcome_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM outcomes WHERE outcome_id = %s", (outcome_id,))
        return cur.fetchone()
