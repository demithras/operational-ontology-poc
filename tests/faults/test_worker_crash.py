"""F12 (worker crash pre-call -> resume safely) / F13 (worker crash
post-call/pre-record -> recover without duplicate effect) — a REAL
`docker compose kill action_worker` (SIGKILL, not a graceful stop) at a
test-armed checkpoint inside the Temporal activity itself
(services/common/test_hooks.py, armed via a direct Postgres write since the
test process and the worker run in different containers), then a real
restart. Temporal's own durable-execution replay (never reconciliation —
see docs/experiment/implementation-notes.md Phase 6 section's
"services/reconciliation ... deliberately narrow scope") is the mechanism
under test.

F12 checkpoint = top of call_external_action (BEFORE the WMS HTTP call is
even built) — killing here and letting call_external_action's own
start_to_close_timeout (20s, no heartbeat_timeout configured for THIS
activity specifically, so the fast common case here and F14's
commit_then_timeout fault are both unaffected) expire is what makes
Temporal reschedule the activity on the restarted worker; that retry then
genuinely calls WMS for the first time.

F13 checkpoint = top of observe_and_finalize — call_external_action's
activity RESULT is already durably recorded in Temporal's history by the
time this checkpoint is reached, so a crash here can NEVER cause
call_external_action to be re-invoked (Temporal replays only the
NOT-YET-completed activity) — the single WMS effect from before the crash
is structurally guaranteed to stay single.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
import psycopg
import pytest

from services.common import test_hooks
from services.decision_service.execution import action_execution_id_for
from tests.faults.helpers import approve_if_needed, propose_transfer, wait_for_terminal_status
from tests.integration.decision_helpers import set_inventory_and_wait

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_CONFIG_ENV = {
    "DOCKER_CONFIG": "/private/tmp/claude-501/-Users-d-surchis-work-operational-ontology-poc/"
    "4651d52d-5874-4c7c-ba8b-4da032dde2a5/scratchpad/docker-config"
}


def _docker_compose(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *args], cwd=REPO_ROOT, env={**os.environ, **DOCKER_CONFIG_ENV},
        capture_output=True, text=True, timeout=timeout,
    )


def _wait_action_worker_healthy(timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get("http://localhost:15486/health", timeout=2.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    return False


def _wait_checkpoint_reached(conn: psycopg.Connection, action_execution_id: str, checkpoint: str, timeout_s: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if test_hooks.reached(conn, action_execution_id, checkpoint):
            return True
        time.sleep(0.3)
    return False


def _kill_and_restart_action_worker() -> None:
    kill = _docker_compose("kill", "action_worker")
    if kill.returncode != 0:
        pytest.skip(f"could not kill action_worker: {kill.stderr}")
    start = _docker_compose("start", "action_worker")
    assert start.returncode == 0, f"failed to restart action_worker: {start.stderr}"
    assert _wait_action_worker_healthy(), "action_worker did not become healthy again after restart"


def test_f12_worker_crash_pre_call_resumes_with_exactly_one_effect(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910701", "WH-B", on_hand=200)
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 25)
    decision = approve_if_needed(decision_client, decision)
    assert decision["status"] == "APPROVED", decision

    action_execution_id = action_execution_id_for(decision["decision_id"])
    test_hooks.arm(ontology_hot_conn, action_execution_id, "pre_call", pause_seconds=25.0)

    r = decision_client.post(f"/decisions/{decision['decision_id']}/execute")
    assert r.status_code == 202, r.text

    assert _wait_checkpoint_reached(ontology_hot_conn, action_execution_id, "pre_call"), (
        "call_external_action never reached its pre_call test hook — nothing to kill mid-flight"
    )

    _kill_and_restart_action_worker()

    # start_to_close_timeout=20s (services/action_worker/workflows.py
    # CALL_EXTERNAL) before Temporal notices the dead worker and reschedules
    # the activity on the restarted one; generous margin beyond that plus
    # the normal CDC-observation wait.
    final = wait_for_terminal_status(decision_client, decision["decision_id"], timeout_s=90.0)
    assert final["status"] == "OBSERVED_SUCCESS", final

    transfer = wms_client.get(f"/transfers/{action_execution_id}").json()
    assert transfer["actual_quantity"] == 25  # exactly one effect — the pre-crash attempt never called WMS at all

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910701", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 175  # 200 - 25, once

    test_hooks.disarm(ontology_hot_conn, action_execution_id)


def test_f13_worker_crash_post_call_pre_record_no_duplicate_effect(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910702", "WH-B", on_hand=200)
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 30)
    decision = approve_if_needed(decision_client, decision)
    assert decision["status"] == "APPROVED", decision

    action_execution_id = action_execution_id_for(decision["decision_id"])
    test_hooks.arm(ontology_hot_conn, action_execution_id, "post_call_pre_record", pause_seconds=15.0)

    r = decision_client.post(f"/decisions/{decision['decision_id']}/execute")
    assert r.status_code == 202, r.text

    assert _wait_checkpoint_reached(ontology_hot_conn, action_execution_id, "post_call_pre_record"), (
        "observe_and_finalize never reached its post_call_pre_record test hook — "
        "WMS was never actually called before the point we meant to crash at"
    )

    # By construction (call_external_action's OWN Temporal activity result
    # is already durably recorded once observe_and_finalize starts), the
    # WMS commit has already happened exactly once at this point.
    transfer_before_kill = wms_client.get(f"/transfers/{action_execution_id}").json()
    assert transfer_before_kill["actual_quantity"] == 30

    _kill_and_restart_action_worker()

    # observe_and_finalize's own heartbeat_timeout (10s,
    # services/action_worker/workflows.py OBSERVE_AND_FINALIZE) is what
    # detects the dead worker here — faster than F12's 20s
    # start_to_close_timeout path.
    final = wait_for_terminal_status(decision_client, decision["decision_id"], timeout_s=60.0)
    assert final["status"] == "OBSERVED_SUCCESS", final

    transfer = wms_client.get(f"/transfers/{action_execution_id}").json()
    assert transfer["actual_quantity"] == 30  # UNCHANGED — call_external_action was never re-invoked

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910702", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 170  # 200 - 30, once — not 200 - 60

    test_hooks.disarm(ontology_hot_conn, action_execution_id)
