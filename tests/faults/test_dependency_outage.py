"""F25 (docs/experiment/spec/09_failure_and_adversarial_matrix.md:
"Temporal unavailable -> execution -> approved decision remains unexecuted,
auditable"). Same real `docker compose stop/start` + try/finally pattern as
tests/integration/test_decision_service_dependency_outage.py's F22-F24.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
import psycopg
import pytest

from tests.faults.helpers import approve_if_needed, propose_transfer, start_execution, wait_for_terminal_status
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


def _wait_temporal_healthy(timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = _docker_compose("ps", "temporal", "--format", "json")
        if '"Health":"healthy"' in result.stdout or "healthy" in result.stdout:
            return True
        time.sleep(1.0)
    return False


def test_f25_temporal_down_leaves_decision_approved_and_unexecuted(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910301", "WH-B", on_hand=150)
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 20)
    decision = approve_if_needed(decision_client, decision)
    assert decision["status"] == "APPROVED"

    stop = _docker_compose("stop", "temporal")
    if stop.returncode != 0:
        pytest.skip(f"could not stop temporal: {stop.stderr}")
    try:
        r = decision_client.post(f"/decisions/{decision['decision_id']}/execute", timeout=15.0)
        assert r.status_code == 503, r.text

        # The decision is unmistakably still APPROVED and unexecuted —
        # never a fabricated EXECUTING/terminal status (acceptance
        # criterion 11).
        still = decision_client.get(f"/decisions/{decision['decision_id']}").json()
        assert still["status"] == "APPROVED", still
    finally:
        start = _docker_compose("start", "temporal")
        assert start.returncode == 0, f"failed to restart temporal: {start.stderr}"
        assert _wait_temporal_healthy(), "temporal did not recover"
        bootstrap = subprocess.run(
            [str(REPO_ROOT / ".venv" / "bin" / "python"), str(REPO_ROOT / "services" / "action_worker" / "bootstrap_temporal.py")],
            cwd=REPO_ROOT, env={**os.environ, **DOCKER_CONFIG_ENV}, capture_output=True, text=True, timeout=60,
        )
        assert bootstrap.returncode == 0, f"bootstrap_temporal.py failed after temporal restart: {bootstrap.stderr}"

    # Auditable + genuinely recoverable: the SAME still-APPROVED decision
    # executes normally once Temporal is back, with no manual intervention
    # beyond the retry.
    start_execution(decision_client, decision["decision_id"])
    final = wait_for_terminal_status(decision_client, decision["decision_id"])
    assert final["status"] == "OBSERVED_SUCCESS", final
