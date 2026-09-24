"""F22-F24, F26 — docs/experiment/spec/09_failure_and_adversarial_matrix.md:
RDF4J/OpenFGA/OPA temporarily unavailable, and a stalled hot-projection
pipeline, must each fail the governed proposal SAFELY with an explicit
status, never fabricated certainty (acceptance criterion 11). Same `docker
compose stop/start` + try/finally pattern as
tests/integration/test_cdc_ingestion.py's RDF4J-outage test.

F26 (Phase 5 fix: watermark-based evidence freshness) is now simulated by
actually stalling a real pipeline component — stopping
`services/projection_builder` so `current_inventory.computed_at` stops
advancing — rather than editing a row's `as_of` via SQL. This is the
mechanism docs/experiment/spec/09's own staleness test describes ("pause the
connector, stop the builder") once freshness stopped being a per-row
property. Since freshness no longer depends on how recently a row was
touched, F22-F24 also no longer need the freshness-retry wrapper this file
used to import — propose() is called directly.

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

from seed import db_env
from services.ingestion import readiness
from tests.integration.decision_helpers import inventory_unchanged, set_inventory_and_wait

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
    """Phase 7 (docs/adr/0004-openfga-historical-model-and-tuple-snapshot.md):
    OpenFGA now runs on the `postgres` datastore engine, so a plain
    container restart (this function's own caller, F23 below) no longer
    wipes anything — this is now a defensive, idempotent no-op in the
    common case (services/decision_service/bootstrap_openfga.py's own
    content-dedup means re-running it never creates a redundant model when
    nothing changed). Kept, and now also re-runs migrations/v2_to_v3/migrate_authz.py,
    for the one real scenario where it still matters: openfga's FIRST-EVER
    startup before either script has run at all. Found the hard way why
    running only the v1 bootstrap here isn't enough: it used to leave the
    v2 (senior_approver / can_approve_large_transfer_v2) model unrestored
    after F23 wiped the (then still `memory`-engine) store, 403ing a LATER
    test in the same session that needed V3-era approval authority."""
    for script in ("services/decision_service/bootstrap_openfga.py", "migrations/v2_to_v3/migrate_authz.py"):
        result = subprocess.run(
            [str(REPO_ROOT / ".venv" / "bin" / "python"), str(REPO_ROOT / script)],
            cwd=REPO_ROOT, env={**os.environ, **DOCKER_CONFIG_ENV}, capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"{script} failed after openfga restart: {result.stderr}"


def _verify_openfga_converged() -> None:
    """"Wait for convergence", OpenFGA's own analogue of
    readiness.wait_for_fresh_hot_projection: a real Check against a KNOWN
    tuple (supervisor-1's migrated senior_approver authority) must resolve
    ALLOWED, not just "the process answers /healthz" — proves the store
    actually has real data behind it, not merely that the HTTP server is
    up."""
    from services.decision_service import authz

    base_url = db_env.openfga_api_url()
    store_id = authz.resolve_store_id(base_url)
    assert store_id is not None, "openfga store not resolvable after restart"
    model_id = authz.resolve_latest_authorization_model_id(base_url, store_id)
    assert model_id is not None, "no authorization model resolvable after restart"
    result = authz.check(base_url, store_id, "can_approve_large_transfer_v2", "warehouse:WH-A", "user", "supervisor-1", model_id)
    assert result.outcome == authz.ALLOWED, f"openfga did not converge to a working, populated store: {result}"


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
        # Phase 5 fix: RDF4J answering its own health check is NOT the same
        # as services/ingestion and services/projection_builder (both
        # independent processes reading/writing RDF4J) having actually
        # caught back up — leaving this test before they do lets a stale
        # window leak into whichever test runs next. See
        # tests/integration/test_cdc_ingestion.py's identical fix for the
        # full empirical write-up (11-19s observed stalls).
        readiness.wait_for_ingestion_watermarks(db_env.ingestion_health_url(), timeout_s=30.0)
        readiness.wait_for_fresh_hot_projection(db_env.ontology_hot_dsn(), timeout_s=30.0)

    assert inventory_unchanged(wms_client, sku, "WH-B", 100)


def test_f23_openfga_down_denies_authorization_explicitly(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, rdf4j_client,
):
    """Phase 8 step 0 (acceptance criterion A.11): an OpenFGA outage means
    the authorization gate never ANSWERED — GATE_UNAVAILABLE (HTTP 503),
    never the fabricated-looking DENIED_AUTHORIZATION a gate that actually
    answered would produce. Still fail-closed (0 effects — asserted below),
    still fully governed (a real Decision IS written, still replayable —
    see the PASS_FAIL_CLOSED_VERIFIED assertion at the end, its own new
    replay class for exactly this case: `services/decision_service/replay.py`)."""
    sku = "SKU-900702"
    stop = _docker_compose("stop", "openfga")
    if stop.returncode != 0:
        pytest.skip(f"could not stop openfga: {stop.stderr}")
    decision_id = None
    try:
        part = set_inventory_and_wait(wms_client, ontology_hot_conn, sku, "WH-B", on_hand=100)
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
        body = r.json()
        assert body["status"] == "GATE_UNAVAILABLE", body
        assert body["unavailable_gate"] == "authorization", body
        assert body["authorization_result"]["outcome"] == "UNAVAILABLE"
        decision_id = body["decision_id"]
    finally:
        start = _docker_compose("start", "openfga")
        assert start.returncode == 0, f"failed to restart openfga: {start.stderr}"
        assert _wait_healthy("openfga", "http://localhost:15481/healthz"), "openfga did not recover"
        # Phase 7: OpenFGA now runs on the `postgres` datastore engine — a
        # restart no longer wipes its store/model/tuples (docs/adr/0004),
        # verified by tests/faults/test_openfga_persistence.py directly.
        # _rebootstrap_openfga() is now a defensive, idempotent no-op in
        # the common case; _verify_openfga_converged() is the REAL
        # assertion this finally block relies on — a live Check against
        # known data, not just an HTTP 200 health response, so a later
        # test in this same session never silently inherits an
        # unpopulated store.
        _rebootstrap_openfga()
        _verify_openfga_converged()

    assert inventory_unchanged(wms_client, sku, "WH-B", 100)

    # Phase 8 step 0: the GATE_UNAVAILABLE decision persisted above must
    # still replay honestly — never FAIL for "not reproducing" an outage
    # that is now resolved (`docs/experiment/spec/07_versioning_and_replay.md`,
    # `services/decision_service/replay.py`'s PASS_FAIL_CLOSED_VERIFIED
    # class). OpenFGA is back up by this point (the finally block above
    # already re-verified convergence), so this also proves the fix works
    # with the dependency both down (at propose time) and later recovered
    # (at replay time) — the actual sequence F23 exists to model.
    from services.decision_service.replay import replay_decision

    assert decision_id is not None
    replay_result = replay_decision(decision_id, ontology_hot_conn, rdf4j_client, db_env.openfga_api_url())
    assert replay_result.status == "PASS_FAIL_CLOSED_VERIFIED", replay_result.as_dict()
    assert replay_result.replay["zero_effects_linked"] is True
    assert replay_result.replay["evidence_hash_match"] is True


def test_f24_opa_down_denies_policy_explicitly(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, rdf4j_client,
):
    """Phase 8 step 0: same GATE_UNAVAILABLE/PASS_FAIL_CLOSED_VERIFIED
    treatment as test_f23 above, for the policy gate."""
    sku = "SKU-900703"
    stop = _docker_compose("stop", "opa")
    if stop.returncode != 0:
        pytest.skip(f"could not stop opa: {stop.stderr}")
    decision_id = None
    try:
        part = set_inventory_and_wait(wms_client, ontology_hot_conn, sku, "WH-B", on_hand=100)
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
        body = r.json()
        assert body["status"] == "GATE_UNAVAILABLE", body
        assert body["unavailable_gate"] == "policy", body
        assert body["policy_result"]["outcome"] == "UNAVAILABLE"
        decision_id = body["decision_id"]
    finally:
        start = _docker_compose("start", "opa")
        assert start.returncode == 0, f"failed to restart opa: {start.stderr}"
        assert _wait_healthy("opa", "http://localhost:15482/health"), "opa did not recover"
        # "Wait for convergence", OPA's analogue: --watch needs a moment to
        # reload the mounted contracts/policies/ tree after a fresh start —
        # a real policy evaluation (not just HTTP 200 on /health) proves
        # the bundle is actually served again, not merely that the process
        # answered.
        _wait_opa_policy_evaluates()

    assert inventory_unchanged(wms_client, sku, "WH-B", 100)

    # Phase 8 step 0 — same replay proof as test_f23 above, for the policy gate.
    from services.decision_service.replay import replay_decision

    assert decision_id is not None
    replay_result = replay_decision(decision_id, ontology_hot_conn, rdf4j_client, db_env.openfga_api_url(), db_env.opa_base_url())
    assert replay_result.status == "PASS_FAIL_CLOSED_VERIFIED", replay_result.as_dict()
    assert replay_result.replay["zero_effects_linked"] is True
    assert replay_result.replay["evidence_hash_match"] is True


def _wait_opa_policy_evaluates(timeout_s: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_body = None
    while time.monotonic() < deadline:
        try:
            r = httpx.post(
                f"{db_env.opa_base_url()}/v1/data/factory/inventory/transfer/result",
                json={"input": {
                    "parameters": {"quantity": 10},
                    "evidence": {"source_available": 100, "safety_stock": 10, "freshness_status": "FRESH",
                                 "source_quality_status": "OK", "destination_quality_status": "OK"},
                    "config": {"approval_threshold_units": 100},
                }},
                timeout=3.0,
            )
            last_body = r.json()
            if r.status_code == 200 and (last_body.get("result") or {}).get("decision") == "allow":
                return
        except httpx.HTTPError as exc:
            last_body = str(exc)
        time.sleep(0.5)
    raise AssertionError(f"opa never resumed evaluating the transfer_inventory bundle: {last_body}")


def test_f26_stalled_projection_builder_yields_insufficient_evidence(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    """F26 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
    "hot projection stale -> freshness visible; policy may reject") under
    the Phase 5 watermark fix: stopping services/projection_builder freezes
    every hot-projection row's `computed_at` — ingestion keeps draining
    Debezium heartbeats just fine (its own watermark stays fresh), but the
    COMBINED pipeline watermark (services/decision_service/evidence.py:
    `min(ingestion_watermark, computed_at)`) correctly goes stale once
    `computed_at` falls behind `max_evidence_freshness_s`, independent of
    whether the underlying source row itself ever changes."""
    sku = "SKU-900704"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, sku, "WH-B", on_hand=100)

    stop = _docker_compose("stop", "projection_builder")
    if stop.returncode != 0:
        pytest.skip(f"could not stop projection_builder: {stop.stderr}")
    try:
        # max_evidence_freshness_s is 5s (contracts/actions/v1/
        # transfer_inventory.yaml) — wait comfortably past it so this isn't
        # racing the builder's own last pre-stop rebuild cycle.
        time.sleep(8.0)
        r = decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "user", "id": "planner-1"},
                "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
            },
            timeout=15.0,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "INSUFFICIENT_EVIDENCE", body
        assert "source_available_fresh" in body["evidence_snapshot"]["missing"]
        src_fact = body["evidence_snapshot"]["facts_used"]["current_source_inventory"]
        assert src_fact["freshness_status"] == "STALE"
    finally:
        start = _docker_compose("start", "projection_builder")
        assert start.returncode == 0, f"failed to restart projection_builder: {start.stderr}"
        assert _wait_healthy("projection_builder", "http://localhost:15485/health"), "projection_builder did not recover"
        # Phase 5 fix: the HTTP health check only proves the PROCESS is up,
        # not that its first post-restart build has landed — wait for
        # `computed_at` to actually be fresh before this test hands the
        # (shared) stack to whichever test runs next.
        readiness.wait_for_fresh_hot_projection(db_env.ontology_hot_dsn(), timeout_s=30.0)

    assert inventory_unchanged(wms_client, sku, "WH-B", 100)
