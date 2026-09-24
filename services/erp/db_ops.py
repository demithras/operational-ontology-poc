"""Query/mutation functions for the fake ERP service. Raw SQL via psycopg —
no ORM, so the exact statement executed is always visible."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()


def _body_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def apply_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def list_suppliers(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM suppliers ORDER BY supplier_id")
        return cur.fetchall()


def get_supplier(conn: psycopg.Connection, supplier_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        return cur.fetchone()


def list_parts(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM parts ORDER BY part_id")
        return cur.fetchall()


def get_part(conn: psycopg.Connection, part_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM parts WHERE part_id = %s", (part_id,))
        return cur.fetchone()


def list_purchase_orders(conn: psycopg.Connection, status: Optional[str] = None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        if status:
            cur.execute("SELECT * FROM purchase_orders WHERE status = %s ORDER BY po_id", (status,))
        else:
            cur.execute("SELECT * FROM purchase_orders ORDER BY po_id")
        return cur.fetchall()


def get_purchase_order(conn: psycopg.Connection, po_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM purchase_orders WHERE po_id = %s", (po_id,))
        po = cur.fetchone()
        if po is None:
            return None
        cur.execute(
            "SELECT part_id, qty, destination_warehouse FROM purchase_order_lines WHERE po_id = %s ORDER BY id",
            (po_id,),
        )
        po["lines"] = cur.fetchall()
        return po


def delay_purchase_order(
    conn: psycopg.Connection, po_id: str, new_expected_at: int, reason: str
) -> tuple[str, Optional[dict[str, Any]]]:
    """Apply the supplier-delay event (docs/experiment/spec/03_domain_scenario.md
    "Event"). Returns (outcome, updated_row) where outcome is one of
    "OK" | "NOT_FOUND" | "TERMINAL"."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM purchase_orders WHERE po_id = %s FOR UPDATE", (po_id,))
        po = cur.fetchone()
        if po is None:
            conn.rollback()
            return "NOT_FOUND", None
        if po["status"] in ("RECEIVED", "CANCELLED"):
            conn.rollback()
            return "TERMINAL", po
        cur.execute(
            """
            UPDATE purchase_orders
            SET expected_at = %s, status = 'DELAYED', delay_reason = %s,
                version = version + 1, updated_at = now()
            WHERE po_id = %s
            RETURNING *
            """,
            (new_expected_at, reason, po_id),
        )
        updated = cur.fetchone()
        conn.commit()
        return "OK", updated


def expedite_purchase_order(
    conn: psycopg.Connection, po_id: str, action_execution_id: str, expedite_fee: int
) -> tuple[str, Optional[dict[str, Any]]]:
    """Phase 6 (contracts/actions/v1/expedite_purchase_order.yaml
    "external_operation: {system: ERP, operation: expedite_purchase_order}").
    Domain rule (a deliberate, documented simplification — no separate
    "target expedited date" parameter exists on the ActionType): expediting
    restores the PO's ORIGINALLY PROMISED arrival (`expected_at :=
    promised_at`) and un-delays it back to OPEN. `expedite_fee` is recorded
    for audit only; it does not change the arithmetic.

    Returns (outcome, row) where outcome is "OK" | "NOT_FOUND" | "TERMINAL"
    | "REPLAYED" | "CONFLICT" — the last two per the idempotency contract
    (same action_execution_id + same body -> REPLAYED with the ORIGINAL
    result; same key + different body -> CONFLICT, 409)."""
    body_hash = _body_hash({"po_id": po_id, "expedite_fee": expedite_fee})
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (action_execution_id,))
        cur.execute("SELECT * FROM purchase_order_actions WHERE action_execution_id = %s", (action_execution_id,))
        existing = cur.fetchone()
        if existing is not None:
            conn.commit()  # releases the advisory lock
            if existing["body_hash"] == body_hash:
                return "REPLAYED", existing["result"]
            return "CONFLICT", None

        cur.execute("SELECT * FROM purchase_orders WHERE po_id = %s FOR UPDATE", (po_id,))
        po = cur.fetchone()
        if po is None:
            conn.rollback()
            return "NOT_FOUND", None
        if po["status"] in ("RECEIVED", "CANCELLED"):
            conn.rollback()
            return "TERMINAL", po

        cur.execute(
            """
            UPDATE purchase_orders
            SET expected_at = promised_at, status = 'OPEN', delay_reason = NULL,
                version = version + 1, updated_at = now()
            WHERE po_id = %s
            RETURNING *
            """,
            (po_id,),
        )
        updated = cur.fetchone()
        result = {**updated, "action_execution_id": action_execution_id, "expedite_fee": expedite_fee}
        cur.execute(
            "INSERT INTO purchase_order_actions (action_execution_id, po_id, action, body_hash, result) "
            "VALUES (%s, %s, 'EXPEDITE', %s, %s)",
            (action_execution_id, po_id, body_hash, json.dumps(result, default=str)),
        )
        conn.commit()
        return "OK", result
