"""Query/mutation functions for the fake MES service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()

TERMINAL_STATUSES = ("DONE", "CANCELLED")


def apply_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def list_production_lines(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM production_lines ORDER BY line_id")
        return cur.fetchall()


def get_production_line(conn: psycopg.Connection, line_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM production_lines WHERE line_id = %s", (line_id,))
        return cur.fetchone()


def list_work_orders(conn: psycopg.Connection, status: Optional[str] = None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        if status:
            cur.execute("SELECT * FROM work_orders WHERE status = %s ORDER BY work_order_id", (status,))
        else:
            cur.execute("SELECT * FROM work_orders ORDER BY work_order_id")
        return cur.fetchall()


def get_work_order(conn: psycopg.Connection, work_order_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM work_orders WHERE work_order_id = %s", (work_order_id,))
        wo = cur.fetchone()
        if wo is None:
            return None
        cur.execute(
            "SELECT part_id, qty FROM bom_requirements WHERE work_order_id = %s ORDER BY id",
            (work_order_id,),
        )
        wo["requirements"] = cur.fetchall()
        return wo


def reschedule_work_order(
    conn: psycopg.Connection, work_order_id: str, new_planned_start: int
) -> tuple[str, Optional[dict[str, Any]]]:
    """Returns (outcome, row) where outcome is "OK" | "NOT_FOUND" | "TERMINAL".
    Rescheduling a DONE/CANCELLED work order is forbidden
    (docs/experiment/spec/03_domain_scenario.md state-machine invariants)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM work_orders WHERE work_order_id = %s FOR UPDATE", (work_order_id,))
        wo = cur.fetchone()
        if wo is None:
            conn.rollback()
            return "NOT_FOUND", None
        if wo["status"] in TERMINAL_STATUSES:
            conn.rollback()
            return "TERMINAL", wo
        cur.execute(
            """
            UPDATE work_orders
            SET planned_start = %s, version = version + 1, updated_at = now()
            WHERE work_order_id = %s
            RETURNING *
            """,
            (new_planned_start, work_order_id),
        )
        updated = cur.fetchone()
        conn.commit()
        return "OK", updated
