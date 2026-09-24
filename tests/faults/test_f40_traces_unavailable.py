"""F40 (docs/experiment/spec/09_failure_and_adversarial_matrix.md: "trace/
log unavailable -> business correctness survives; canonical provenance
remains in data model"). Stops the real otel-collector container and
proves propose -> approve -> execute still succeeds completely normally
through decision_service — see services/common/tracing.py's own docstring
for the mechanism (span export is best-effort, on a background thread,
with a short exporter timeout; nothing on the request path blocks on it).

Canonical provenance ("remains in data model") is proved by the SAME
assertions every other decision-service test already makes: the returned
decision record itself carries decision_id/action_execution_id/etc
regardless of whether tracing exists at all — this test doesn't need a
separate proof of that half, it is simply what `propose()`/`execute()`
already return on every call in this whole repo.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
import psycopg
import pytest

from tests.faults.helpers import approve_if_needed
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


def test_propose_approve_execute_unaffected_by_otel_collector_outage(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection,
):
    stop = _docker_compose("stop", "otel-collector")
    if stop.returncode != 0:
        pytest.skip(f"could not stop otel-collector (may not be deployed in this environment): {stop.stderr}")

    try:
        part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-975401", "WH-B", on_hand=60)
        r = decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "user", "id": "planner-1"},
                "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 1},
                "context": {},
            },
        )
        assert r.status_code == 200, f"propose() failed while otel-collector was down: {r.status_code} {r.text}"
        decision = r.json()
        assert decision["status"] in ("APPROVED", "REQUIRES_APPROVAL"), decision

        decision = approve_if_needed(decision_client, decision)
        assert decision["status"] == "APPROVED", decision

        r2 = decision_client.post(f"/decisions/{decision['decision_id']}/execute")
        assert r2.status_code == 202, f"execute() failed while otel-collector was down: {r2.status_code} {r2.text}"
        body = r2.json()
        # Canonical provenance is unaffected: the real identifiers are
        # returned exactly as they would be with tracing fully available.
        assert body["decision_id"] == decision["decision_id"]
        assert body["action_execution_id"]
    finally:
        start = _docker_compose("start", "otel-collector")
        assert start.returncode == 0, f"failed to restart otel-collector: {start.stderr}"
