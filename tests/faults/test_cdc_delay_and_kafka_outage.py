"""F18 (CDC delayed -> AWAITING_OBSERVATION, never success, while paused ->
resume -> converges) and F21 (Kafka temporarily down -> no fabricated
freshness, proposals become INSUFFICIENT_EVIDENCE via the watermark ->
recovery after restart).

F18 pauses the WMS Debezium connector via the real Kafka Connect REST API
(services/ingestion/register_connectors.py's own naming: connector name
"oo-poc-wms-connector", from contracts/cdc/v1/wms-connector.json) — WMS
itself still commits the transfer for real (the fault is entirely in the
OBSERVATION path, not the command path), so the worker's own 30s CDC poll
(services/action_worker/activities.py::_poll_wms_transfer_record) times
out -> OUTCOME_UNKNOWN / outcome.reconciliationState=AWAITING_OBSERVATION.
Resuming the connector lets the delayed event finally land in RDF4J;
services/reconciliation's independent poll loop (H12, the ONLY thing that
mutates an OUTCOME_UNKNOWN decision — see
docs/experiment/implementation-notes.md Phase 6 section's "deliberately
narrow scope") then converges it to OBSERVED_SUCCESS without any human/test
intervention beyond the resume itself.

F21 stops the whole `kafka` container — same `docker compose stop/start` +
watermark-staleness pattern as
tests/integration/test_decision_service_dependency_outage.py::test_f26_stalled_projection_builder_yields_insufficient_evidence,
except the SOURCE of staleness is the whole CDC transport rather than one
downstream consumer.
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
from services.decision_service.execution import action_execution_id_for
from services.ingestion import readiness
from tests.faults.helpers import approve_if_needed, propose_transfer, start_execution, wait_for_terminal_status
from tests.integration.decision_helpers import inventory_unchanged, set_inventory_and_wait

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


def test_f18_paused_wms_connector_yields_awaiting_observation_then_reconciles(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    connect_url = db_env.connect_rest_url()
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910801", "WH-B", on_hand=180)
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, 15)
    decision = approve_if_needed(decision_client, decision)
    assert decision["status"] == "APPROVED", decision
    action_execution_id = action_execution_id_for(decision["decision_id"])

    with httpx.Client(timeout=10.0) as client:
        pause = client.put(f"{connect_url}/connectors/{WMS_CONNECTOR_NAME}/pause")
    if pause.status_code not in (200, 202, 204):
        pytest.skip(f"could not pause {WMS_CONNECTOR_NAME}: HTTP {pause.status_code} {pause.text}")

    try:
        start_execution(decision_client, decision["decision_id"])
        # observation.timeout PT30S (contracts/actions/v1/transfer_inventory.yaml)
        # plus margin for the worker's own RDF round trips.
        final = wait_for_terminal_status(decision_client, decision["decision_id"], timeout_s=45.0)
        assert final["status"] == "OUTCOME_UNKNOWN", final  # never a fabricated OBSERVED_SUCCESS while paused

        outcome_id = f"O-{action_execution_id}"
        outcome = decision_client.get(f"/outcomes/{outcome_id}").json()
        assert outcome["reconciliationState"] == "AWAITING_OBSERVATION", outcome

        # WMS itself DID commit for real — the fault is purely in the
        # observation path, never the command path (F18 is a CDC-layer
        # fault, not a WMS-layer one).
        transfer = wms_client.get(f"/transfers/{action_execution_id}").json()
        assert transfer["status"] == "COMMITTED"
        assert transfer["actual_quantity"] == 15
    finally:
        with httpx.Client(timeout=10.0) as client:
            resume = client.put(f"{connect_url}/connectors/{WMS_CONNECTOR_NAME}/resume")
        assert resume.status_code in (200, 202, 204), f"failed to resume {WMS_CONNECTOR_NAME}: {resume.text}"
        readiness.connectors_running(timeout_s=60.0)

    # services/reconciliation's own poll loop (2s interval) picks up the
    # now-delivered WmsTransferRecord and converges the decision — no
    # further action from this test beyond the resume above.
    deadline = time.monotonic() + 30.0
    status = None
    while time.monotonic() < deadline:
        status = decision_client.get(f"/decisions/{decision['decision_id']}").json()["status"]
        if status == "OBSERVED_SUCCESS":
            break
        time.sleep(1.0)
    assert status == "OBSERVED_SUCCESS", f"reconciliation never converged the decision (last status={status!r})"

    lot = wms_client.get("/inventory_lots", params={"part": "SKU-910801", "warehouse_id": "WH-B"}).json()[0]
    assert lot["on_hand"] == 165  # 180 - 15, exactly once


def test_f21_kafka_down_yields_insufficient_evidence_via_watermark_then_recovers(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    sku = "SKU-910802"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, sku, "WH-B", on_hand=90)

    stop = _docker_compose("stop", "kafka")
    if stop.returncode != 0:
        pytest.skip(f"could not stop kafka: {stop.stderr}")
    try:
        # max_evidence_freshness_s is 5s (contracts/actions/v1/
        # transfer_inventory.yaml) — comfortably past it before proposing,
        # same margin as F26's stalled-projection-builder test.
        time.sleep(8.0)

        # A real bug was found and fixed while building this test:
        # services/decision_service/evidence.py::_resolve_source_inventory_with_freshness
        # used to hold its caller's Postgres transaction open (with an
        # AccessShareLock on current_inventory) across its ENTIRE up-to-8s
        # staleness-retry loop, which under a SUSTAINED outage (exactly
        # this scenario — Kafka down for the whole request, not just one
        # poll gap) reliably deadlocked against
        # services/projection_builder's own TRUNCATE order
        # (docs/experiment/implementation-notes.md Phase 6 section's
        # documented-as-rare AB-BA window, made near-certain by the long
        # hold). Fixed by committing between retry attempts (that function
        # is read-only; nothing is lost). A short retry loop remains here
        # as ordinary defense-in-depth against decision_service's own 3x
        # DeadlockDetected retry occasionally still losing a race, not
        # because it is expected to fire.
        import random

        body = None
        last_status = None
        for _attempt in range(10):
            r = decision_client.post(
                "/decisions/propose",
                json={
                    "action_type": "transfer_inventory",
                    "actor": {"type": "user", "id": "planner-1"},
                    "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 20},
                },
                timeout=30.0,
            )
            last_status = r.status_code
            if r.status_code == 200:
                body = r.json()
                break
            time.sleep(random.uniform(0.4, 2.9))
        assert body is not None, f"propose() kept failing across retries while kafka was down (last HTTP status={last_status})"
        assert body["status"] == "INSUFFICIENT_EVIDENCE", body
        assert "source_available_fresh" in body["evidence_snapshot"]["missing"]
        src_fact = body["evidence_snapshot"]["facts_used"]["current_source_inventory"]
        assert src_fact["freshness_status"] == "STALE"
    finally:
        start = _docker_compose("start", "kafka")
        assert start.returncode == 0, f"failed to restart kafka: {start.stderr}"
        # Kafka has no HTTP health endpoint at all — connectors_running/
        # watermarks below are the REAL readiness proof (same "prove real
        # API readiness, not just a bare connect" pattern as
        # bootstrap_temporal.py), not a bare TCP/HTTP probe.
        readiness.connectors_running(timeout_s=90.0)
        readiness.wait_for_ingestion_watermarks(db_env.ingestion_health_url(), timeout_s=60.0)
        readiness.wait_for_fresh_hot_projection(db_env.ontology_hot_dsn(), timeout_s=30.0)

    assert inventory_unchanged(wms_client, sku, "WH-B", 90)
