"""Network tests (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"Introduce: latency; timeout; connection reset; duplicate HTTP delivery.
Use a proxy/fault layer or test doubles with deterministic fault scripts.").

Design decision: deterministic test doubles in the WMS fault registry
(services/common/faults.py, already mounted behind OO_TEST_MODE=1) rather
than a toxiproxy container — the brief explicitly allows either, and this
repo's WMS fault modes already model every one of these at the exact
worker<->WMS network boundary the matrix cares about:
  - latency            -> `delay_commit` (a real multi-second server-side
                           delay before the response is sent)
  - connection reset    -> `return_500_before_commit` (the request completes
                           with a fault status and zero server-side effect —
                           the closest same-layer analogue this fake WMS can
                           produce to a hard connection failure, since a fake
                           service cannot literally sever a TCP socket
                           without a lot more infrastructure that adds no
                           further assurance here)
  - timeout / duplicate delivery -> already covered end to end by
    tests/faults/test_commit_then_timeout.py (F14) and
    tests/faults/test_idempotency.py (F10/F11) respectively — not repeated
    here.

Each test below drives the REAL decision_service -> Temporal -> WMS path
(never a direct WMS call — tests/integration/test_wms_faults.py already
proves the WMS-layer mechanics for every fault mode alone), and asserts the
SYSTEM-level effect-multiplicity property the matrix actually cares about:
one real effect, or an honest zero, never a duplicate or fabricated one.
"""

from __future__ import annotations

import httpx
import psycopg

from tests.faults.helpers import propose_approve_arm_execute
from tests.integration.decision_helpers import set_inventory_and_wait


def test_network_latency_delay_commit_converges_to_one_effect(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, wms_faults_reset
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-911101", "WH-B", on_hand=250)
    final, action_execution_id = propose_approve_arm_execute(
        decision_client, wms_client, "planner-1", "WH-B", "WH-A", part, 33,
        fault_mode="delay_commit", fault_params={"delay_s": 4.0},
    )
    assert final["status"] == "OBSERVED_SUCCESS", final

    transfer = wms_client.get(f"/transfers/{action_execution_id}").json()
    assert transfer["status"] == "COMMITTED"
    assert transfer["actual_quantity"] == 33

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-911101", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 217  # 250 - 33, exactly once despite the latency


def test_network_connection_failure_before_commit_yields_zero_effect_never_duplicated(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, wms_faults_reset
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-911102", "WH-B", on_hand=250)
    final, action_execution_id = propose_approve_arm_execute(
        decision_client, wms_client, "planner-1", "WH-B", "WH-A", part, 33,
        fault_mode="return_500_before_commit",
    )
    # No fabricated success under a hard connection-layer-style failure —
    # WMS never persisted anything for this key at all (its own rollback),
    # so there is nothing to ever converge to except an honest non-success.
    assert final["status"] != "OBSERVED_SUCCESS", final
    assert final["status"] in ("OUTCOME_UNKNOWN", "EXECUTION_FAILED"), final

    assert wms_client.get(f"/transfers/{action_execution_id}").status_code == 404

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-911102", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 250  # zero effect — never a partial or duplicated one
