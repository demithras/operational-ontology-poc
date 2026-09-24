"""Core `POST /transfers` logic: idempotency, row-locking, and fault
injection (docs/experiment/spec/06_decision_and_action_runtime.md "WMS fake
API requirements").

Concurrency design:
  * A Postgres transaction-scoped advisory lock keyed by
    hashtextextended(action_execution_id, 0) serializes every request that
    shares the same idempotency key — including the very first one, before
    any row for it exists — which a plain `SELECT ... FOR UPDATE` cannot do
    (you cannot lock a row that doesn't exist yet). The lock is released
    automatically on COMMIT/ROLLBACK.
  * Two DIFFERENT action_execution_ids racing for the same inventory lot are
    serialized by an ordinary `SELECT ... FOR UPDATE` on that (already
    existing) inventory_lots row — source and destination lots are always
    locked in warehouse_id order so opposite-direction concurrent transfers
    cannot deadlock each other.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

from services.common.faults import ArmedFault, registry


def _body_hash(source: str, destination: str, part: str, quantity: int) -> str:
    payload = json.dumps(
        {"source": source, "destination": destination, "part": part, "quantity": quantity},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _advisory_lock(cur: psycopg.Cursor, key: str) -> None:
    cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,))


def _transfer_response(row: dict[str, Any], replayed: bool = False) -> dict[str, Any]:
    out = dict(row)
    out["replayed"] = replayed
    return out


def create_transfer(
    conn: psycopg.Connection,
    action_execution_id: str,
    source_warehouse: str,
    destination_warehouse: str,
    part: str,
    quantity: int,
    test_mode: bool,
    reverses: Optional[str] = None,
) -> tuple[int, dict[str, Any]]:
    """Returns (http_status, response_body)."""
    if quantity <= 0:
        return 422, {"error": "quantity must be positive"}
    if source_warehouse == destination_warehouse:
        return 422, {"error": "source and destination must differ"}

    body_hash = _body_hash(source_warehouse, destination_warehouse, part, quantity)

    with conn.cursor(row_factory=dict_row) as cur:
        _advisory_lock(cur, action_execution_id)

        cur.execute("SELECT * FROM transfers WHERE action_execution_id = %s", (action_execution_id,))
        existing = cur.fetchone()
        if existing is not None and existing["body_hash"] == body_hash:
            if (not test_mode) or registry.idempotency_check_enabled():
                conn.commit()  # releases the advisory lock
                return 200, _transfer_response(existing, replayed=True)
            # Phase 10a item 1 deliberately-injected bug (test-mode only,
            # see services/common/faults.py::FaultRegistry's idempotency
            # toggle): idempotency check "disabled" -> re-apply the SAME
            # inventory mutation again instead of deduping. This models a
            # caller whose retry contract exists (same logical request) but
            # whose SERVER has no dedup at all — the inventory side effect
            # doubles, silently, which is exactly the H4 property
            # ("one logical action creates at most one intended business
            # effect") tests/stateful is built to catch. The `transfers` row
            # itself is left untouched (mutating it would collide with its
            # own PRIMARY KEY) — only inventory_lots moves twice.
            wh_pair = sorted([source_warehouse, destination_warehouse])
            cur.execute(
                """
                SELECT * FROM inventory_lots
                WHERE part = %s AND warehouse_id = ANY(%s)
                ORDER BY warehouse_id
                FOR UPDATE
                """,
                (part, wh_pair),
            )
            dup_rows = {r["warehouse_id"]: r for r in cur.fetchall()}
            dup_source = dup_rows.get(source_warehouse)
            dup_dest = dup_rows.get(destination_warehouse)
            dup_qty = existing["actual_quantity"]
            if dup_source is not None and dup_qty > 0:
                cur.execute(
                    "UPDATE inventory_lots SET on_hand = on_hand - %s, version = version + 1, updated_at = now() "
                    "WHERE lot_id = %s",
                    (dup_qty, dup_source["lot_id"]),
                )
            if dup_dest is not None and dup_qty > 0:
                cur.execute(
                    "UPDATE inventory_lots SET on_hand = on_hand + %s, version = version + 1, updated_at = now() "
                    "WHERE lot_id = %s",
                    (dup_qty, dup_dest["lot_id"]),
                )
            conn.commit()
            duped = dict(existing)
            duped["note"] = "TEST-MODE BUG: idempotency check disabled — mutation re-applied, not deduped"
            return 200, _transfer_response(duped, replayed=False)
        if existing is not None:
            conn.commit()  # releases the advisory lock
            return 409, {
                "error": "action_execution_id already used with a different request body",
                "action_execution_id": action_execution_id,
            }

        fault: Optional[ArmedFault] = registry.resolve(action_execution_id) if test_mode else None

        if fault is not None and fault.mode == "return_500_before_commit":
            conn.rollback()
            return 500, {"error": "simulated fault: return_500_before_commit", "fault_mode": fault.mode}

        wh_pair = sorted([source_warehouse, destination_warehouse])
        cur.execute(
            """
            SELECT * FROM inventory_lots
            WHERE part = %s AND warehouse_id = ANY(%s)
            ORDER BY warehouse_id
            FOR UPDATE
            """,
            (part, wh_pair),
        )
        rows = {r["warehouse_id"]: r for r in cur.fetchall()}
        source_lot = rows.get(source_warehouse)
        if source_lot is None:
            conn.rollback()
            return 404, {"error": f"no inventory lot for part={part} at warehouse={source_warehouse}"}

        quantity_to_apply = quantity
        status = "COMMITTED"
        if fault is not None and fault.mode == "partial_commit":
            quantity_to_apply = min(int(fault.params.get("actual_quantity", max(1, quantity - 10))), quantity)
            status = "PARTIAL"

        if source_lot["available"] < quantity_to_apply:
            cur.execute(
                """
                INSERT INTO transfers
                    (action_execution_id, source_warehouse, destination_warehouse, part,
                     requested_quantity, actual_quantity, status, body_hash, fault_mode_applied,
                     reverses_action_execution_id)
                VALUES (%s, %s, %s, %s, %s, 0, 'FAILED', %s, %s, %s)
                RETURNING *
                """,
                (
                    action_execution_id, source_warehouse, destination_warehouse, part,
                    quantity, body_hash, fault.mode if fault else None, reverses,
                ),
            )
            failed = cur.fetchone()
            conn.commit()
            return 409, {
                "error": "insufficient available stock at source warehouse",
                "available": source_lot["available"],
                "requested": quantity,
                "transfer": _transfer_response(failed),
            }

        cur.execute(
            "UPDATE inventory_lots SET on_hand = on_hand - %s, version = version + 1, updated_at = now() "
            "WHERE lot_id = %s",
            (quantity_to_apply, source_lot["lot_id"]),
        )

        dest_lot = rows.get(destination_warehouse)
        if dest_lot is None:
            cur.execute(
                """
                INSERT INTO inventory_lots (lot_id, part, warehouse_id, on_hand, reserved, quality_status)
                VALUES (%s, %s, %s, %s, 0, 'OK')
                """,
                (f"LOT-{destination_warehouse}-{part}", part, destination_warehouse, quantity_to_apply),
            )
        else:
            cur.execute(
                "UPDATE inventory_lots SET on_hand = on_hand + %s, version = version + 1, updated_at = now() "
                "WHERE lot_id = %s",
                (quantity_to_apply, dest_lot["lot_id"]),
            )

        cur.execute(
            """
            INSERT INTO transfers
                (action_execution_id, source_warehouse, destination_warehouse, part,
                 requested_quantity, actual_quantity, status, body_hash, fault_mode_applied,
                 reverses_action_execution_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                action_execution_id, source_warehouse, destination_warehouse, part,
                quantity, quantity_to_apply, status, body_hash, fault.mode if fault else None, reverses,
            ),
        )
        row = cur.fetchone()

        if fault is not None and fault.mode == "return_200_without_commit":
            conn.rollback()
            fabricated = dict(row)
            fabricated["note"] = "fault: return_200_without_commit — never persisted"
            return 200, _transfer_response(fabricated)

        if fault is not None and fault.mode == "delay_commit":
            time.sleep(float(fault.params.get("delay_s", 2)))

        conn.commit()

        if fault is not None and fault.mode == "commit_then_timeout":
            # Already committed; simulate the confirmation arriving late.
            time.sleep(float(fault.params.get("timeout_s", 6)))

        response = _transfer_response(row)
        if fault is not None and fault.mode == "duplicate_response":
            response["fault_note"] = "duplicate_response: re-POST the same body to verify dedup"
        return 200, response


def reverse_transfer(
    conn: psycopg.Connection,
    original_action_execution_id: str,
    reversal_action_execution_id: str,
    test_mode: bool,
) -> tuple[int, dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM transfers WHERE action_execution_id = %s", (original_action_execution_id,))
        original = cur.fetchone()
    conn.commit()
    if original is None:
        return 404, {"error": "original transfer not found"}
    if original["status"] not in ("COMMITTED", "PARTIAL"):
        return 409, {"error": f"cannot reverse a transfer with status {original['status']}"}

    return create_transfer(
        conn,
        action_execution_id=reversal_action_execution_id,
        source_warehouse=original["destination_warehouse"],
        destination_warehouse=original["source_warehouse"],
        part=original["part"],
        quantity=original["actual_quantity"],
        test_mode=test_mode,
        reverses=original_action_execution_id,
    )
