"""docs/adr/0004-openfga-historical-model-and-tuple-snapshot.md: OpenFGA
now runs on the `postgres` datastore engine (not `memory`) specifically so
a container restart never wipes the authorization store — found necessary
live when this repo's OWN F22-F26 outage tests
(tests/integration/test_decision_service_dependency_outage.py), which stop
the real `openfga` container as part of F23, silently regressed a LATER
test in the same `make test` session (a real approval check 403'd because
the memory store had been wiped and only partially re-bootstrapped).

Proves the fix directly: restart the real openfga container, then assert
(a) the store id and the LATEST model id are IDENTICAL before and after —
nothing was lost, nothing new was silently created; (b) an EXISTING
approval check (an actor who was already granted authority before the
restart) still succeeds; (c) replaying a real V1 corpus decision still
PASSes end to end.
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
from services.decision_service import authz
from services.decision_service.replay import replay_decision

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


def _wait_healthy(url: str, timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2.0).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(1.0)
    return False


def test_openfga_restart_preserves_store_model_and_existing_checks(
    decision_client: httpx.Client, historical_corpus, ontology_hot_conn, rdf4j_client, opa_base_url,
):
    db_env.load_dotenv()
    base_url = db_env.openfga_api_url()

    store_id_before = authz.resolve_store_id(base_url)
    assert store_id_before is not None, "openfga store not resolvable before restart"
    model_id_before = authz.resolve_latest_authorization_model_id(base_url, store_id_before)
    assert model_id_before is not None, "no authorization model resolvable before restart"

    # An approval check that must already succeed BEFORE the restart —
    # supervisor-1 was migrated (migrations/v2_to_v3/migrate_authz.py) onto
    # senior_approver, so can_approve_large_transfer_v2 on WH-A is ALLOWED.
    before = authz.check(base_url, store_id_before, "can_approve_large_transfer_v2", "warehouse:WH-A", "user", "supervisor-1", model_id_before)
    assert before.outcome == authz.ALLOWED, before

    stop = _docker_compose("stop", "openfga")
    if stop.returncode != 0:
        pytest.skip(f"could not stop openfga: {stop.stderr}")
    try:
        start = _docker_compose("start", "openfga")
        assert start.returncode == 0, f"failed to restart openfga: {start.stderr}"
        assert _wait_healthy(f"{base_url}/healthz"), "openfga did not recover"
    finally:
        pass  # nothing to restore -- the whole point is persistence needs no rebootstrap

    store_id_after = authz.resolve_store_id(base_url)
    model_id_after = authz.resolve_latest_authorization_model_id(base_url, store_id_after)

    assert store_id_after == store_id_before, (
        f"store id changed across an openfga restart ({store_id_before!r} -> {store_id_after!r}) "
        "-- the postgres datastore is not actually persisting"
    )
    assert model_id_after == model_id_before, (
        f"latest authorization model id changed across an openfga restart ({model_id_before!r} -> "
        f"{model_id_after!r}) with no bootstrap script run in between"
    )

    after = authz.check(base_url, store_id_after, "can_approve_large_transfer_v2", "warehouse:WH-A", "user", "supervisor-1", model_id_after)
    assert after.outcome == authz.ALLOWED, after

    # A real V1 corpus decision (proposed long before this test ran) must
    # still replay PASS — its OWN pinned authorization_model_id must still
    # resolve against the SAME persistent store.
    v1_decision_id = historical_corpus["v1"]["decision_ids"][0]
    result = replay_decision(v1_decision_id, ontology_hot_conn, rdf4j_client, base_url, opa_base_url)
    assert result.status == "PASS", result.as_dict()
