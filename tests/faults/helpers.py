"""Shared helpers for tests/faults/ — drives the REAL end-to-end path
(decision_service propose -> approve -> execute -> Temporal -> WMS -> CDC ->
reconciliation), never a direct WMS call (that is tests/integration/test_wms_faults.py's
job, at the WMS layer alone). `action_execution_id` is deterministic from
`decision_id` (services/decision_service/execution.py::action_execution_id_for),
so a WMS fault can be armed for the EXACT id a not-yet-started execution
will use.
"""

from __future__ import annotations

import time

import httpx

from services.decision_service.execution import action_execution_id_for

TERMINAL_STATUSES = {"OBSERVED_SUCCESS", "DIVERGED", "OUTCOME_UNKNOWN", "EXECUTION_FAILED"}


def arm_wms_fault(wms_client: httpx.Client, mode: str, action_execution_id: str, params: dict | None = None) -> None:
    r = wms_client.post(
        "/_test/faults/arm",
        json={"mode": mode, "scope": "action_execution_id", "action_execution_id": action_execution_id, "params": params or {}},
    )
    assert r.status_code == 200, r.text


def propose_transfer(
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
    assert r.status_code == 200, r.text
    return r.json()


def approve_if_needed(decision_client: httpx.Client, decision: dict, approver_id: str = "supervisor-1") -> dict:
    if decision["status"] != "REQUIRES_APPROVAL":
        return decision
    r = decision_client.post(
        f"/decisions/{decision['decision_id']}/approve",
        json={"approver_id": approver_id, "decision_content_hash": decision["decision_content_hash"]},
    )
    assert r.status_code == 200, r.text
    return r.json()


def start_execution(decision_client: httpx.Client, decision_id: str) -> dict:
    r = decision_client.post(f"/decisions/{decision_id}/execute")
    assert r.status_code == 202, r.text
    return r.json()


def wait_for_terminal_status(decision_client: httpx.Client, decision_id: str, timeout_s: float = 45.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last = decision_client.get(f"/decisions/{decision_id}").json()
    while time.monotonic() < deadline:
        if last["status"] in TERMINAL_STATUSES:
            return last
        time.sleep(1.0)
        last = decision_client.get(f"/decisions/{decision_id}").json()
    return last  # caller asserts — an honest timeout, never a fabricated status


def propose_approve_arm_execute(
    decision_client: httpx.Client,
    wms_client: httpx.Client,
    actor_id: str,
    source: str,
    destination: str,
    part: str,
    quantity: int,
    fault_mode: str | None,
    fault_params: dict | None = None,
    approver_id: str = "supervisor-1",
    wait_timeout_s: float = 50.0,
) -> tuple[dict, str]:
    """The common shape every fault test in this package needs: propose,
    approve if required, arm a WMS fault for the exact action_execution_id
    this decision's execution will use, execute, and wait for a terminal
    decision status. Returns (final_decision, action_execution_id)."""
    decision = propose_transfer(decision_client, actor_id, source, destination, part, quantity)
    decision = approve_if_needed(decision_client, decision, approver_id)
    assert decision["status"] == "APPROVED", decision
    action_execution_id = action_execution_id_for(decision["decision_id"])
    if fault_mode is not None:
        arm_wms_fault(wms_client, fault_mode, action_execution_id, fault_params)
    start_execution(decision_client, decision["decision_id"])
    final = wait_for_terminal_status(decision_client, decision["decision_id"], timeout_s=wait_timeout_s)
    return final, action_execution_id
