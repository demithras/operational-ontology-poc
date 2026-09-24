"""Query/mutation functions for the fake MES service."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()

TERMINAL_STATUSES = ("DONE", "CANCELLED")


def _body_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


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


def reschedule_work_order_with_idempotency(
    conn: psycopg.Connection, work_order_id: str, action_execution_id: str, new_planned_start: int
) -> tuple[str, Optional[dict[str, Any]]]:
    """Phase 6 (contracts/actions/v1/reschedule_work_order.yaml
    external_operation) — the idempotency-key-bearing path services/action_worker
    calls, kept SEPARATE from `reschedule_work_order` above (which stays
    exactly as it was for any caller that doesn't supply one, e.g.
    tests/integration/test_mes_reschedule.py — see services/mes/app.py).
    Returns (outcome, row) where outcome adds "REPLAYED" | "CONFLICT" to
    reschedule_work_order's "OK" | "NOT_FOUND" | "TERMINAL"."""
    body_hash = _body_hash({"work_order_id": work_order_id, "new_planned_start": new_planned_start})
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (action_execution_id,))
        cur.execute("SELECT * FROM work_order_actions WHERE action_execution_id = %s", (action_execution_id,))
        existing = cur.fetchone()
        if existing is not None:
            conn.commit()
            if existing["body_hash"] == body_hash:
                return "REPLAYED", existing["result"]
            return "CONFLICT", None

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
        result = {**updated, "action_execution_id": action_execution_id}
        cur.execute(
            "INSERT INTO work_order_actions (action_execution_id, work_order_id, action, body_hash, result) "
            "VALUES (%s, %s, 'RESCHEDULE', %s, %s)",
            (action_execution_id, work_order_id, body_hash, json.dumps(result, default=str)),
        )
        conn.commit()
        return "OK", result


def set_work_order_for_test(
    conn: psycopg.Connection,
    work_order_id: str,
    priority: str,
    warehouse: str,
    requirements: list[dict[str, Any]],
    status: str = "RELEASED",
    planned_start: int = 0,
    planned_finish: int = 1,
    production_line_id: str = "LINE-00",
) -> dict[str, Any]:
    """Test-mode-only exact upsert of one synthetic work order plus its FULL
    replacement BOM requirement set (docs/experiment/briefs/phase10fix.md
    "self-contained fixtures"). Existing requirement rows for this
    work_order_id are deleted first, then the given set is inserted —
    `bom_requirements` has no UNIQUE(work_order_id, part_id) constraint (see
    services/projection_builder/compute.py's own comment on this), so a
    naive re-insert across repeated calls (a test's fixture re-running
    across separate `make test` invocations against the same long-lived
    stack) would silently accumulate duplicate requirement rows and inflate
    the computed shortage each time. Mounted only behind OO_TEST_MODE=1
    (services/mes/app.py), same convention as
    services/wms/db_ops.py::set_inventory_for_test."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO work_orders
                (work_order_id, production_line_id, status, priority, planned_start, planned_finish, warehouse)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (work_order_id) DO UPDATE
                SET status = EXCLUDED.status,
                    priority = EXCLUDED.priority,
                    planned_start = EXCLUDED.planned_start,
                    planned_finish = EXCLUDED.planned_finish,
                    warehouse = EXCLUDED.warehouse,
                    production_line_id = EXCLUDED.production_line_id,
                    version = work_orders.version + 1,
                    updated_at = now()
            RETURNING *
            """,
            (work_order_id, production_line_id, status, priority, planned_start, planned_finish, warehouse),
        )
        wo = cur.fetchone()

        cur.execute("DELETE FROM bom_requirements WHERE work_order_id = %s", (work_order_id,))
        for req in requirements:
            cur.execute(
                "INSERT INTO bom_requirements (work_order_id, part_id, qty) VALUES (%s, %s, %s)",
                (work_order_id, req["part_id"], req["qty"]),
            )

        cur.execute(
            "SELECT part_id, qty FROM bom_requirements WHERE work_order_id = %s ORDER BY id",
            (work_order_id,),
        )
        wo["requirements"] = cur.fetchall()
    conn.commit()
    return wo
