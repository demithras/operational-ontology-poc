"""W6 (Phase 8 A/B experiment) — the SAME novel cross-system relation as
services/decision_service/forensics.py ("for a given at-risk work order,
which supplier(s) does its shortage trace back to"), as a plain SQL JOIN
over services/baseline/consumer.py's own CDC-replicated tables. Every
column this query joins was ALREADY present in services/baseline/schema.sql
before this file existed — no schema/consumer change required either, the
relational analogue of the ontology variant's "already-mapped triples,
just a new query" situation. See
docs/experiment/implementation-notes.md Phase 8 item 2 (W6) for the
measured effort comparison.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row


def at_risk_suppliers(conn: psycopg.Connection, work_order_id: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT po.supplier_id, l.po_id, l.part
            FROM work_orders wo
            JOIN bom_requirements req ON req.work_order_id = wo.work_order_id
            JOIN purchase_order_lines l ON l.part = req.part AND l.destination_wh = wo.warehouse_id
            JOIN purchase_orders po ON po.po_id = l.po_id
            WHERE wo.work_order_id = %s AND po.status NOT IN ('RECEIVED', 'CANCELLED')
            """,
            (work_order_id,),
        )
        return cur.fetchall()
