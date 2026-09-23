"""Read-only query functions + schema bootstrap for the fake WMS service.
Transfer write logic (idempotency, locking, fault injection) lives in
services/wms/transfers.py — kept separate because it is the one genuinely
tricky piece of Phase 2."""

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


def list_warehouses(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM warehouses ORDER BY warehouse_id")
        return cur.fetchall()


def get_warehouse(conn: psycopg.Connection, warehouse_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM warehouses WHERE warehouse_id = %s", (warehouse_id,))
        return cur.fetchone()


def list_inventory_lots(
    conn: psycopg.Connection, part: Optional[str] = None, warehouse_id: Optional[str] = None
) -> list[dict[str, Any]]:
    clauses = []
    params: list[Any] = []
    if part:
        clauses.append("part = %s")
        params.append(part)
    if warehouse_id:
        clauses.append("warehouse_id = %s")
        params.append(warehouse_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT * FROM inventory_lots {where} ORDER BY lot_id", params)
        return cur.fetchall()


def get_inventory_lot(conn: psycopg.Connection, lot_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM inventory_lots WHERE lot_id = %s", (lot_id,))
        return cur.fetchone()


def get_transfer(conn: psycopg.Connection, action_execution_id: str) -> Optional[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM transfers WHERE action_execution_id = %s", (action_execution_id,))
        return cur.fetchone()


def set_inventory_for_test(
    conn: psycopg.Connection,
    part: str,
    warehouse_id: str,
    on_hand: int,
    reserved: int = 0,
    quality_status: str = "OK",
) -> dict[str, Any]:
    """Test-mode-only exact upsert of one inventory lot, so concurrency/race
    tests (tests/integration/test_wms_concurrency.py) can set up a known
    stock level without depending on seeded data or test execution order.
    Mounted only behind OO_TEST_MODE=1 (services/wms/app.py)."""
    lot_id = f"LOT-TEST-{warehouse_id}-{part}"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO inventory_lots (lot_id, part, warehouse_id, on_hand, reserved, quality_status)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (part, warehouse_id) DO UPDATE
                SET on_hand = EXCLUDED.on_hand,
                    reserved = EXCLUDED.reserved,
                    quality_status = EXCLUDED.quality_status,
                    version = inventory_lots.version + 1,
                    updated_at = now()
            RETURNING *
            """,
            (lot_id, part, warehouse_id, on_hand, reserved, quality_status),
        )
        row = cur.fetchone()
    conn.commit()
    return row
