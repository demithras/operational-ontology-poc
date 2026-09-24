"""F14 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"commit-then-timeout -> WMS -> retry resolves via idempotency/
reconciliation") — end to end through decision_service's real execute() ->
Temporal -> WMS path, not a direct WMS call
(tests/integration/test_wms_faults.py::test_commit_then_timeout_recovers_via_idempotent_replay
already proves the WMS-layer idempotent-replay mechanism alone; this proves
the SYSTEM converges through it).

services/wms/transfers.py's `commit_then_timeout` fault mode COMMITS the
transfer for real, then sleeps `timeout_s` before returning the response.
services/action_worker/activities.py::call_external_action posts to WMS
with a hardcoded 10s httpx client timeout — armed with `timeout_s` > 10s,
the WORKER's own HTTP call genuinely times out client-side even though WMS
already committed server-side. Temporal's CALL_EXTERNAL activity retry
policy (services/action_worker/workflows.py, maximum_attempts=5) then
retries the SAME activity, which re-POSTs the SAME action_execution_id/body
to WMS — WMS's own idempotency (body_hash match) replays the ALREADY-
COMMITTED row instead of committing a second time, so the workflow still
converges to exactly one effect, OBSERVED_SUCCESS.
"""

from __future__ import annotations

import httpx
import psycopg

from tests.faults.helpers import propose_approve_arm_execute
from tests.integration.decision_helpers import set_inventory_and_wait


def test_f14_commit_then_timeout_converges_to_one_effect(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, wms_faults_reset
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910601", "WH-B", on_hand=300)
    final, action_execution_id = propose_approve_arm_execute(
        decision_client, wms_client, "planner-1", "WH-B", "WH-A", part, 45,
        fault_mode="commit_then_timeout", fault_params={"timeout_s": 12.0},
        wait_timeout_s=60.0,
    )
    assert final["status"] == "OBSERVED_SUCCESS", final

    transfer = wms_client.get(f"/transfers/{action_execution_id}").json()
    assert transfer["status"] == "COMMITTED"
    assert transfer["actual_quantity"] == 45  # exactly one 45-unit effect, not zero and not two

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910601", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 255  # 300 - 45, once
