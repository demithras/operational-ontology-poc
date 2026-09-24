"""Phase 10a item 1: real HTTP/infra wrappers for tests/stateful's
RuleBasedStateMachine — one function per verb docs/experiment/briefs/
phase10a.md item 1 names, driving the REAL live services (never a direct
DB write, except the one place noted below).

Scope disclosure (see docs/experiment/implementation-notes.md's Phase 10a
item 1 section for the full reasoning): `change_policy` and `duplicate_cdc`
are NOT implemented as live-mutating rules here.
  - `change_policy` would mean rewriting a mounted OPA bundle file mid-loop
    (OPA runs with `--watch`) — the V1->V2/V2->V3 policy evolution is
    already exercised end-to-end by tests/replay/ (H7/H8), and item 2's
    own POLICY_COMPARATOR mutation test already proves the policy suite
    catches a real comparator change; adding a THIRD, live-mid-loop path
    to the same property was judged not worth the added risk to the
    shared stack within this phase's remaining budget.
  - `duplicate_cdc` (F19) already has dedicated, direct-code-path coverage
    in tests/faults/test_cdc_ordering.py (services.ingestion.store.
    apply_event called twice with an identical envelope) — re-deriving
    that here would not add new evidence, only wall-clock cost.
`restart_service` and `delay_cdc` (docker/Kafka-Connect operations) are
real but BUDGET-CAPPED by the calling machine to fire at most once per
machine instance (see test_live_differential.py) — real infra restarts are
too slow to run unboundedly inside a Hypothesis loop.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_CONFIG_ENV = {
    "DOCKER_CONFIG": "/private/tmp/claude-501/-Users-d-surchis-work-operational-ontology-poc/"
    "4651d52d-5874-4c7c-ba8b-4da032dde2a5/scratchpad/docker-config"
}
WMS_CONNECTOR_NAME = "oo-poc-wms-connector"

CANONICAL_WORK_ORDER = "WO-42"
CANONICAL_PURCHASE_ORDER = "PO-991"


# --- inventory (WMS, real HTTP) --------------------------------------------------


def get_lot(wms_client: httpx.Client, part: str, warehouse: str) -> dict | None:
    rows = wms_client.get("/inventory_lots", params={"part": part, "warehouse_id": warehouse}).json()
    return rows[0] if rows else None


def set_lot(wms_client: httpx.Client, part: str, warehouse: str, on_hand: int, reserved: int) -> dict:
    r = wms_client.post(
        "/_test/inventory/set",
        json={"part": part, "warehouse_id": warehouse, "on_hand": on_hand, "reserved": reserved},
    )
    assert r.status_code == 200, r.text
    return r.json()


def receive_inventory_live(wms_client: httpx.Client, part: str, warehouse: str, qty: int) -> dict:
    """Models a PO receipt landing in WMS: on_hand += qty, reserved
    unchanged. Uses WMS's own test-mode set endpoint (read-then-write —
    there is no dedicated "receive" HTTP verb on the fake WMS API)."""
    lot = get_lot(wms_client, part, warehouse)
    before_on_hand = lot["on_hand"] if lot else 0
    before_reserved = lot["reserved"] if lot else 0
    return set_lot(wms_client, part, warehouse, before_on_hand + qty, before_reserved)


def reserve_inventory_live(wms_client: httpx.Client, part: str, warehouse: str, qty: int) -> tuple[bool, dict | None]:
    """Returns (applied, lot_after). Refuses (like reference_model.
    transitions.reserve_inventory) if available < qty."""
    lot = get_lot(wms_client, part, warehouse)
    if lot is None or (lot["on_hand"] - lot["reserved"]) < qty:
        return False, lot
    return True, set_lot(wms_client, part, warehouse, lot["on_hand"], lot["reserved"] + qty)


def release_inventory_live(wms_client: httpx.Client, part: str, warehouse: str, qty: int) -> tuple[bool, dict | None]:
    lot = get_lot(wms_client, part, warehouse)
    if lot is None or lot["reserved"] < qty:
        return False, lot
    return True, set_lot(wms_client, part, warehouse, lot["on_hand"], lot["reserved"] - qty)


# --- transfer lifecycle (decision_service, real HTTP) -----------------------------


def propose_transfer_live(
    decision_client: httpx.Client, actor_id: str, source: str, destination: str, part: str, quantity: int,
) -> dict:
    r = decision_client.post(
        "/decisions/propose",
        json={
            "action_type": "transfer_inventory",
            "actor": {"type": "user", "id": actor_id},
            "parameters": {"source_warehouse": source, "destination_warehouse": destination, "part": part, "quantity": quantity},
            "context": {},
        },
    )
    assert r.status_code in (200, 503), f"unexpected propose() status {r.status_code}: {r.text}"
    return r.json() if r.status_code == 200 else {"status": "GATE_UNAVAILABLE_HTTP503"}


def approve_transfer_live(decision_client: httpx.Client, decision: dict, approver_id: str = "supervisor-1") -> dict:
    if decision.get("status") != "REQUIRES_APPROVAL":
        return decision
    r = decision_client.post(
        f"/decisions/{decision['decision_id']}/approve",
        json={"approver_id": approver_id, "decision_content_hash": decision["decision_content_hash"]},
    )
    if r.status_code != 200:
        return decision  # denied/unavailable — caller inspects original decision's status
    return r.json()


def execute_transfer_live(decision_client: httpx.Client, decision_id: str) -> dict | None:
    r = decision_client.post(f"/decisions/{decision_id}/execute")
    if r.status_code != 202:
        return None
    return r.json()


def get_decision_live(decision_client: httpx.Client, decision_id: str) -> dict:
    r = decision_client.get(f"/decisions/{decision_id}")
    assert r.status_code == 200, r.text
    return r.json()


# --- work orders (MES, real HTTP) --------------------------------------------------


def pick_work_order(mes_client: httpx.Client, status: str, exclude: str = CANONICAL_WORK_ORDER) -> str | None:
    rows = mes_client.get("/work_orders", params={"status": status}).json()
    for row in rows:
        if row["work_order_id"] != exclude:
            return row["work_order_id"]
    return None


def reschedule_work_order_live(mes_client: httpx.Client, work_order_id: str, new_planned_start: int) -> httpx.Response:
    return mes_client.post(f"/work_orders/{work_order_id}/reschedule", json={"new_planned_start": new_planned_start})


# --- suppliers (ERP, real HTTP) — supplier_delay/supplier_recovery analogs --------


def pick_purchase_order(erp_client: httpx.Client, status: str, exclude: str = CANONICAL_PURCHASE_ORDER) -> str | None:
    rows = erp_client.get("/purchase_orders", params={"status": status}).json()
    for row in rows:
        if row["po_id"] != exclude:
            return row["po_id"]
    return None


def supplier_delay_live(erp_client: httpx.Client, po_id: str, new_expected_at: int, reason: str) -> httpx.Response:
    return erp_client.post(f"/purchase_orders/{po_id}/delay", json={"expected_at": new_expected_at, "reason": reason})


def supplier_recovery_live(erp_client: httpx.Client, po_id: str, action_execution_id: str) -> httpx.Response:
    """The closest live analog to reference_model's supplier_recovery
    ("resolve the delay, resume normal expectation") available on the real
    fake-ERP API is /expedite — see this module's own docstring for why
    there is no separate "recovery" endpoint to call instead."""
    return erp_client.post(f"/purchase_orders/{po_id}/expedite", json={"action_execution_id": action_execution_id})


# --- authorization (OpenFGA, real HTTP) — change_permission -----------------------


def write_grant_tuple(openfga_api_url: str, store_id: str, user: str, relation: str, object_: str) -> None:
    r = httpx.post(
        f"{openfga_api_url}/stores/{store_id}/write",
        json={"writes": {"tuple_keys": [{"user": user, "relation": relation, "object": object_}]}},
        timeout=10.0,
    )
    if r.status_code == 400 and "already exist" in r.text.lower():
        return
    r.raise_for_status()


def delete_grant_tuple(openfga_api_url: str, store_id: str, user: str, relation: str, object_: str) -> None:
    r = httpx.post(
        f"{openfga_api_url}/stores/{store_id}/write",
        json={"deletes": {"tuple_keys": [{"user": user, "relation": relation, "object": object_}]}},
        timeout=10.0,
    )
    if r.status_code == 400 and "did not exist" in r.text.lower():
        return
    r.raise_for_status()


# --- infra faults (docker/Kafka Connect) — restart_service / delay_cdc -----------


def _docker_compose(*args: str, timeout: float = 90.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *args], cwd=REPO_ROOT, env={**os.environ, **DOCKER_CONFIG_ENV},
        capture_output=True, text=True, timeout=timeout,
    )


def restart_service_live(service: str, health_url: str, timeout_s: float = 60.0) -> bool:
    kill = _docker_compose("kill", service)
    if kill.returncode != 0:
        return False
    start = _docker_compose("start", service)
    if start.returncode != 0:
        return False
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(health_url, timeout=2.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    return False


def pause_wms_connector(connect_url: str) -> bool:
    with httpx.Client(timeout=10.0) as client:
        r = client.put(f"{connect_url}/connectors/{WMS_CONNECTOR_NAME}/pause")
    return r.status_code in (200, 202, 204)


def resume_wms_connector(connect_url: str) -> bool:
    with httpx.Client(timeout=10.0) as client:
        r = client.put(f"{connect_url}/connectors/{WMS_CONNECTOR_NAME}/resume")
    return r.status_code in (200, 202, 204)
