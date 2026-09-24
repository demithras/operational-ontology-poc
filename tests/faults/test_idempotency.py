"""F10 (duplicate API request -> same logical effect once) / F11 (concurrent
duplicate -> unique idempotency enforcement) — end to end through
decision_service's real execute() -> Temporal -> WMS path, not a direct WMS
call (tests/integration/test_wms_faults.py covers the WMS layer alone).

Temporal's own workflow-id uniqueness (id=action_execution_id,
services/decision_service/execution.py) is the FIRST idempotency layer: a
duplicate execute() call for the same decision reuses the SAME workflow
rather than starting a second one. WMS's action_execution_id unique
constraint (services/wms/schema.sql) is the SECOND, independent layer —
this file proves BOTH hold end to end.
"""

from __future__ import annotations

import threading

import httpx
import psycopg

from services.decision_service.execution import action_execution_id_for
from tests.faults.helpers import approve_if_needed, propose_transfer, start_execution, wait_for_terminal_status
from tests.integration.decision_helpers import set_inventory_and_wait


def test_f10_duplicate_execute_call_has_one_effect(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910101", "WH-B", on_hand=300)
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 40)
    decision = approve_if_needed(decision_client, decision)
    assert decision["status"] == "APPROVED"

    r1 = start_execution(decision_client, decision["decision_id"])
    r2 = start_execution(decision_client, decision["decision_id"])  # duplicate call, F10
    assert r1["action_execution_id"] == r2["action_execution_id"]
    assert r1["started_now"] is True
    assert r2["started_now"] is False  # reused the SAME Temporal workflow, never started a second one

    final = wait_for_terminal_status(decision_client, decision["decision_id"])
    assert final["status"] == "OBSERVED_SUCCESS", final

    action_execution_id = action_execution_id_for(decision["decision_id"])
    transfer = wms_client.get(f"/transfers/{action_execution_id}").json()
    assert transfer["actual_quantity"] == 40  # exactly one 40-unit effect, not two

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910101", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 260  # 300 - 40, not 300 - 80


def test_f11_concurrent_duplicate_execute_calls_have_one_effect(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910102", "WH-B", on_hand=300)
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 35)
    decision = approve_if_needed(decision_client, decision)
    assert decision["status"] == "APPROVED"

    results: list[dict] = []
    errors: list[Exception] = []

    def _call():
        try:
            with httpx.Client(base_url=str(decision_client.base_url), timeout=15.0) as c:
                r = c.post(f"/decisions/{decision['decision_id']}/execute")
                results.append(r.json())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert not errors, errors
    assert len(results) == 8
    action_execution_ids = {r["action_execution_id"] for r in results}
    assert action_execution_ids == {action_execution_id_for(decision["decision_id"])}
    assert sum(1 for r in results if r["started_now"]) == 1  # exactly one caller actually started it

    final = wait_for_terminal_status(decision_client, decision["decision_id"])
    assert final["status"] == "OBSERVED_SUCCESS", final

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910102", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 265  # 300 - 35, exactly once
