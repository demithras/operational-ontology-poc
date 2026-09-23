"""Query/mutation functions for the fake ERP service. Raw SQL via psycopg —
no ORM, so the exact statement executed is always visible."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()


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
