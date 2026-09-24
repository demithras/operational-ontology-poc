"""Kill tests (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"Kill tests": "At selected workflow checkpoints, automatically terminate:
decision service; Temporal worker; projection builder; reconciliation
worker. Restart and assert convergence."). Temporal worker (action_worker)
kill/restart is F12/F13 (tests/faults/test_worker_crash.py) — this file
covers the other three, each real `docker compose kill` (SIGKILL, not a
graceful stop) + restart + a convergence proof specific to that service's
own job.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
import psycopg
import pytest

from seed import db_env
from services.ingestion import readiness
from tests.faults.helpers import approve_if_needed, propose_transfer, start_execution, wait_for_terminal_status
from tests.integration.decision_helpers import set_inventory_and_wait

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_CONFIG_ENV = {
    "DOCKER_CONFIG": "/private/tmp/claude-501/-Users-d-surchis-work-operational-ontology-poc/"
    "4651d52d-5874-4c7c-ba8b-4da032dde2a5/scratchpad/docker-config"
}
WMS_CONNECTOR_NAME = "oo-poc-wms-connector"


def _docker_compose(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *args], cwd=REPO_ROOT, env={**os.environ, **DOCKER_CONFIG_ENV},
        capture_output=True, text=True, timeout=timeout,
    )


def _wait_health(url: str, timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    return False


def _kill_and_restart(service: str, health_url: str) -> None:
    kill = _docker_compose("kill", service)
    if kill.returncode != 0:
        pytest.skip(f"could not kill {service}: {kill.stderr}")
    start = _docker_compose("start", service)
    assert start.returncode == 0, f"failed to restart {service}: {start.stderr}"
    assert _wait_health(health_url), f"{service} did not become healthy again after restart"


def test_kill_restart_decision_service_convergence(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    """decision_service is stateless (spec 06: "the Postgres row is only an
    index" of the RDF4J-authoritative record) — killing it mid-flight loses
    only IN-FLIGHT HTTP requests (a real connection error to the caller,
    never a fabricated response), and a restart resumes normal service with
    no manual recovery step: the SAME already-converged inventory/RDF state
    is still there, untouched."""
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-911001", "WH-B", on_hand=60)

    kill = _docker_compose("kill", "decision_service")
    if kill.returncode != 0:
        pytest.skip(f"could not kill decision_service: {kill.stderr}")
    try:
        with httpx.Client(base_url=str(decision_client.base_url), timeout=5.0) as dead_client:
            with pytest.raises(httpx.HTTPError):
                dead_client.post(
                    "/decisions/propose",
                    json={
                        "action_type": "transfer_inventory",
                        "actor": {"type": "user", "id": "planner-1"},
                        "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 10},
                    },
                )
    finally:
        start = _docker_compose("start", "decision_service")
        assert start.returncode == 0, f"failed to restart decision_service: {start.stderr}"
        assert _wait_health("http://localhost:15410/health"), "decision_service did not become healthy again"

    # Convergence: the SAME still-good inventory data is still visible, and
    # a fresh request against the restarted process succeeds normally, with
    # no reseed/rebootstrap step of any kind.
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 10)
    decision = approve_if_needed(decision_client, decision)
    assert decision["status"] == "APPROVED", decision
    start_execution(decision_client, decision["decision_id"])
    final = wait_for_terminal_status(decision_client, decision["decision_id"])
    assert final["status"] == "OBSERVED_SUCCESS", final


def test_kill_restart_projection_builder_convergence(wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection):
    """Kill projection_builder mid-poll-cycle, make a real WMS change WHILE
    it is down (so the change queues up unread), restart it, and prove the
    hot projection still catches up to the new value with no manual
    rebuild step — never permanently stuck on the pre-kill value."""
    kill = _docker_compose("kill", "projection_builder")
    if kill.returncode != 0:
        pytest.skip(f"could not kill projection_builder: {kill.stderr}")
    try:
        r = wms_client.post("/_test/inventory/set", json={"part": "SKU-911002", "warehouse_id": "WH-B", "on_hand": 314})
        assert r.status_code == 200, r.text
        time.sleep(3.0)  # give it a real chance to (wrongly) show up while builder is down
    finally:
        start = _docker_compose("start", "projection_builder")
        assert start.returncode == 0, f"failed to restart projection_builder: {start.stderr}"
        assert _wait_health("http://localhost:15485/health"), "projection_builder did not become healthy again"

    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-911002", "WH-B", on_hand=314, timeout_s=30.0)
    assert part == "PX-811002"


def test_kill_restart_reconciliation_convergence(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    """Put a real decision into OUTCOME_UNKNOWN (same WMS-connector-pause
    mechanism as F18), kill reconciliation WHILE it sits unresolved, restart
    it, then resume the connector — reconciliation's OWN poll loop (H12,
    the only thing that ever mutates an OUTCOME_UNKNOWN decision) must
    still pick the delayed observation up and converge, with no
    reconciliation-specific recovery step beyond the restart."""
    connect_url = db_env.connect_rest_url()
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-911003", "WH-B", on_hand=140)
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 10)
    decision = approve_if_needed(decision_client, decision)
    assert decision["status"] == "APPROVED", decision

    with httpx.Client(timeout=10.0) as client:
        pause = client.put(f"{connect_url}/connectors/{WMS_CONNECTOR_NAME}/pause")
    if pause.status_code not in (200, 202, 204):
        pytest.skip(f"could not pause {WMS_CONNECTOR_NAME}: HTTP {pause.status_code} {pause.text}")
    # Kafka Connect's pause is ASYNC — the task can take a moment to
    # actually stop consuming after the REST call returns 202. Settle
    # before triggering execute() so the WMS commit's own CDC event is
    # genuinely blocked, not racing a still-draining task.
    time.sleep(2.0)

    try:
        start_execution(decision_client, decision["decision_id"])
        stuck = wait_for_terminal_status(decision_client, decision["decision_id"], timeout_s=45.0)
        assert stuck["status"] == "OUTCOME_UNKNOWN", stuck

        _kill_and_restart("reconciliation", "http://localhost:15487/health")
    finally:
        with httpx.Client(timeout=10.0) as client:
            resume = client.put(f"{connect_url}/connectors/{WMS_CONNECTOR_NAME}/resume")
        assert resume.status_code in (200, 202, 204), f"failed to resume {WMS_CONNECTOR_NAME}: {resume.text}"
        readiness.connectors_running(timeout_s=60.0)

    deadline = time.monotonic() + 30.0
    status = None
    while time.monotonic() < deadline:
        status = decision_client.get(f"/decisions/{decision['decision_id']}").json()["status"]
        if status == "OBSERVED_SUCCESS":
            break
        time.sleep(1.0)
    assert status == "OBSERVED_SUCCESS", f"reconciliation never converged after its own restart (last status={status!r})"
