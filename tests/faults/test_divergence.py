"""F15 (200 without commit -> never OBSERVED_SUCCESS), F16 (partial commit
-> DIVERGED + compensation path), F17 (wrong quantity -> DIVERGED) — end to
end through decision_service's execute() -> Temporal -> WMS path.

F16/F17 share one observable shape from services/action_worker/outcome_eval.py's
predicate (actual_quantity != requested_quantity), so one fault
(`partial_commit`) proves both: WMS committed something, but not what was
requested.
"""

from __future__ import annotations

import httpx
import psycopg

from services.decision_service.execution import action_execution_id_for
from tests.faults.helpers import propose_approve_arm_execute
from tests.integration.decision_helpers import set_inventory_and_wait


def test_f15_200_without_commit_never_observed_success(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, wms_faults_reset
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910201", "WH-B", on_hand=200)
    final, action_execution_id = propose_approve_arm_execute(
        decision_client, wms_client, "planner-1", "WH-B", "WH-A", part, 30,
        fault_mode="return_200_without_commit",
    )
    assert final["status"] != "OBSERVED_SUCCESS", final
    # WMS itself never persisted a row for this fault (services/wms/transfers.py:
    # "return_200_without_commit" rolls back after fabricating the response) —
    # so there is nothing for the CDC poll to ever observe; the worker's own
    # 30s wait expires -> OUTCOME_UNKNOWN, an honest "cannot confirm", not a
    # fabricated success.
    assert final["status"] == "OUTCOME_UNKNOWN", final
    assert wms_client.get(f"/transfers/{action_execution_id}").status_code == 404

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910201", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 200  # zero effect


def test_f16_f17_partial_commit_diverges_and_compensates(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, wms_faults_reset
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910202", "WH-B", on_hand=200)
    final, action_execution_id = propose_approve_arm_execute(
        decision_client, wms_client, "planner-1", "WH-B", "WH-A", part, 60,
        fault_mode="partial_commit", fault_params={"actual_quantity": 50},
    )
    assert final["status"] == "DIVERGED", final

    transfer = wms_client.get(f"/transfers/{action_execution_id}").json()
    assert transfer["status"] == "PARTIAL"
    assert transfer["requested_quantity"] == 60
    assert transfer["actual_quantity"] == 50

    # compensation.mode: compensatable (contracts/actions/v1/transfer_inventory.yaml)
    # -> services/action_worker/activities.py auto-reverses the PARTIAL
    # effect via WMS's own reverse_transfer.
    outcome_id = f"O-{action_execution_id}"
    outcome = decision_client.get(f"/outcomes/{outcome_id}").json()
    assert outcome["compensationStatus"] == "COMPENSATED", outcome

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910202", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 200  # the 50-unit partial effect was reversed back to the original 200
