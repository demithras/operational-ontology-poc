"""F22-F24 — docs/experiment/spec/09_failure_and_adversarial_matrix.md:
RDF4J/OpenFGA/OPA each temporarily unavailable must fail the governed
proposal SAFELY with an explicit status, never fabricated certainty
(acceptance criterion 11). Same `docker compose stop/start` + try/finally
pattern as tests/integration/test_cdc_ingestion.py's RDF4J-outage test.

Real container stop/start, so these are slower and more invasive than the
rest of tests/integration/test_decision_service_*.py — kept in their own
file so a failure here doesn't obscure the (fast, header-only) gate tests.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import httpx
import psycopg
import pytest

from tests.integration.decision_helpers import inventory_unchanged, propose_with_freshness_retry, set_inventory_and_wait

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


def _rebootstrap_openfga() -> None:
    result = subprocess.run(
        [str(REPO_ROOT / ".venv" / "bin" / "python"), str(REPO_ROOT / "services" / "decision_service" / "bootstrap_openfga.py")],
        cwd=REPO_ROOT, env={**os.environ, **DOCKER_CONFIG_ENV}, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"bootstrap_openfga.py failed after openfga restart: {result.stderr}"


def _wait_healthy(service: str, health_url: str, timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(health_url, timeout=2.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    return False


def test_f22_rdf4j_down_fails_proposal_safely(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    sku = "SKU-900701"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, sku, "WH-B", on_hand=100)
    stop = _docker_compose("stop", "rdf4j")
    if stop.returncode != 0:
        pytest.skip(f"could not stop rdf4j: {stop.stderr}")
    try:
        r = decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "user", "id": "planner-1"},
                "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
            },
            timeout=15.0,
        )
        assert r.status_code == 503, r.text
    finally:
        start = _docker_compose("start", "rdf4j")
        assert start.returncode == 0, f"failed to restart rdf4j: {start.stderr}"
        assert _wait_healthy("rdf4j", "http://localhost:15480/rdf4j-server/protocol"), "rdf4j did not recover"

    assert inventory_unchanged(wms_client, sku, "WH-B", 100)


def test_f23_openfga_down_denies_authorization_explicitly(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    sku = "SKU-900702"
    # Stop openfga BEFORE setting up inventory (not after): evidence
    # gathering doesn't need OpenFGA at all, but the freshness window this
    # test's propose() call depends on is only 5s wide
    # (contracts/actions/v1/transfer_inventory.yaml) — a `docker compose
    # stop` subprocess call takes real wall-clock seconds, and running it
    # AFTER set_inventory_and_wait's freshness bump reliably ate the whole
    # window (found empirically: this test failed with INSUFFICIENT_EVIDENCE
    # instead of DENIED_AUTHORIZATION on the first attempt).
    stop = _docker_compose("stop", "openfga")
    if stop.returncode != 0:
        pytest.skip(f"could not stop openfga: {stop.stderr}")
    try:
        part = set_inventory_and_wait(wms_client, ontology_hot_conn, sku, "WH-B", on_hand=100)
        r = propose_with_freshness_retry(
            ontology_hot_conn, part, "WH-B",
            lambda: decision_client.post(
                "/decisions/propose",
                json={
                    "action_type": "transfer_inventory",
                    "actor": {"type": "user", "id": "planner-1"},
                    "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
                },
                timeout=15.0,
            ),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "DENIED_AUTHORIZATION"
        assert body["authorization_result"]["outcome"] == "UNAVAILABLE"
    finally:
        start = _docker_compose("start", "openfga")
        assert start.returncode == 0, f"failed to restart openfga: {start.stderr}"
        assert _wait_healthy("openfga", "http://localhost:15481/healthz"), "openfga did not recover"
        # OpenFGA runs with the `memory` datastore engine (docker-compose.yml)
        # — a restart wipes its store/model/tuples entirely, same as a real
        # operational restart would. Re-bootstrap so later tests in this
        # file (and this whole test session) see a populated store again,
        # exactly like `make up` does after a fresh container start.
        _rebootstrap_openfga()

    assert inventory_unchanged(wms_client, sku, "WH-B", 100)


def test_f24_opa_down_denies_policy_explicitly(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    sku = "SKU-900703"
    # Same ordering fix as test_f23 above: stop the dependency BEFORE the
    # freshness-sensitive inventory setup, not after.
    stop = _docker_compose("stop", "opa")
    if stop.returncode != 0:
        pytest.skip(f"could not stop opa: {stop.stderr}")
    try:
        part = set_inventory_and_wait(wms_client, ontology_hot_conn, sku, "WH-B", on_hand=100)
        r = propose_with_freshness_retry(
            ontology_hot_conn, part, "WH-B",
            lambda: decision_client.post(
                "/decisions/propose",
                json={
                    "action_type": "transfer_inventory",
                    "actor": {"type": "user", "id": "planner-1"},
                    "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
                },
                timeout=15.0,
            ),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "DENIED_POLICY"
        assert body["policy_result"]["outcome"] == "UNAVAILABLE"
    finally:
        start = _docker_compose("start", "opa")
        assert start.returncode == 0, f"failed to restart opa: {start.stderr}"
        assert _wait_healthy("opa", "http://localhost:15482/health"), "opa did not recover"

    assert inventory_unchanged(wms_client, sku, "WH-B", 100)
