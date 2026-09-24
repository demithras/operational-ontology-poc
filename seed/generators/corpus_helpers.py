"""Shared HTTP/DB helpers for seed/generators/historical_corpus.py — the
Phase 7 historical corpus generator (docs/experiment/spec/07_versioning_and_replay.md).
Mirrors tests/faults/helpers.py and tests/integration/decision_helpers.py's
own propose/approve/execute/wait patterns (host-side, against the real
running decision_service/wms, never a shortcut path) so the corpus is
created through the SAME real pipeline the fault-test suite already proves
correct — not a second, parallel implementation.
"""

from __future__ import annotations

import re
import time

import httpx
import psycopg

TERMINAL_STATUSES = {
    "OBSERVED_SUCCESS", "DIVERGED", "OUTCOME_UNKNOWN", "EXECUTION_FAILED",
    "ACTION_VERSION_INVALIDATED",
}
DENIED_OR_INSUFFICIENT = {"INSUFFICIENT_EVIDENCE", "DENIED_AUTHORIZATION", "DENIED_POLICY"}

_SKU_OFFSET = 100000
_SKU_RE = re.compile(r"^SKU-(\d{6})$")


def sku_to_canonical(sku: str) -> str:
    m = _SKU_RE.match(sku)
    if not m:
        raise ValueError(f"{sku!r} not a SKU-###### id")
    return f"PX-{int(m.group(1)) - _SKU_OFFSET:04d}"


def set_inventory_and_wait(
    wms: httpx.Client, conn: psycopg.Connection, sku: str, warehouse: str,
    on_hand: int, reserved: int = 0, quality_status: str = "OK", timeout_s: float = 90.0,
) -> str:
    canonical = sku_to_canonical(sku)
    r = wms.post("/_test/inventory/set", json={
        "part": sku, "warehouse_id": warehouse, "on_hand": on_hand,
        "reserved": reserved, "quality_status": quality_status,
    })
    r.raise_for_status()

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT on_hand, reserved FROM current_inventory WHERE part=%s AND warehouse=%s",
                (canonical, warehouse),
            )
            row = cur.fetchone()
        # CRITICAL: commit (or, if autocommit, this is a no-op) between
        # polls — an open, uncommitted SELECT-only transaction still holds
        # an AccessShareLock on current_inventory for the transaction's
        # whole lifetime under Postgres, which BLOCKS services/projection_builder's
        # own TRUNCATE-then-rebuild cycle indefinitely (same lock-order
        # issue services/decision_service/evidence.py's own freshness-retry
        # loop already documents and fixes the same way). Without this, a
        # long-lived polling connection can silently freeze the table at
        # whatever it looked like when the FIRST select opened the
        # transaction — found empirically while building this generator
        # (a write converged in 3s once this fix was in place; before it,
        # 175+ seconds and still not converged).
        conn.commit()
        if row and row[0] == on_hand and row[1] == reserved:
            return canonical
        time.sleep(0.5)
    raise TimeoutError(f"current_inventory never converged for {canonical}/{warehouse}")


def arm_wms_fault(wms: httpx.Client, mode: str, action_execution_id: str) -> None:
    r = wms.post("/_test/faults/arm", json={
        "mode": mode, "scope": "action_execution_id", "action_execution_id": action_execution_id, "params": {},
    })
    r.raise_for_status()


def propose(
    dec: httpx.Client, actor_id: str, source: str, destination: str, part: str, quantity: int,
    actor_type: str = "user",
) -> dict:
    r = dec.post("/decisions/propose", json={
        "action_type": "transfer_inventory",
        "actor": {"type": actor_type, "id": actor_id},
        "parameters": {"source_warehouse": source, "destination_warehouse": destination, "part": part, "quantity": quantity},
        "context": {},
    })
    r.raise_for_status()
    return r.json()


def approve_if_needed(dec: httpx.Client, decision: dict, approver_id: str = "supervisor-1") -> dict:
    if decision["status"] != "REQUIRES_APPROVAL":
        return decision
    r = dec.post(f"/decisions/{decision['decision_id']}/approve", json={
        "approver_id": approver_id, "decision_content_hash": decision["decision_content_hash"],
    })
    r.raise_for_status()
    return r.json()


def action_execution_id_for(decision_id: str) -> str:
    return f"AX-{decision_id}"


def start_execution(dec: httpx.Client, decision_id: str) -> None:
    r = dec.post(f"/decisions/{decision_id}/execute")
    r.raise_for_status()


def wait_for_terminal(dec: httpx.Client, decision_id: str, timeout_s: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last = dec.get(f"/decisions/{decision_id}").json()
    while time.monotonic() < deadline:
        if last["status"] in TERMINAL_STATUSES:
            return last
        time.sleep(1.0)
        last = dec.get(f"/decisions/{decision_id}").json()
    return last
