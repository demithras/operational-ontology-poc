"""Phase 10a step 0c: confirm approve() returns 503 (not a fabricated 403)
when OpenFGA is unreachable or still warming up right after a restart —
Phase 8 step 0's intent (acceptance criterion A.11: "component failure
causes explicit unavailable/pending/unknown state, not fabricated
certainty"), exercised live here for the specific "restart, then approve
immediately" window docs/experiment/briefs/phase10a.md step 0c calls out.

services/decision_service/app.py already implements this correctly (read,
not written, by this phase): `_current_store_id()` re-resolves the OpenFGA
store on every request (never cached — see its own docstring), and
`decisions_approve()` raises HTTPException(503, ...) when store_id is None
or when authz.check()'s outcome is UNAVAILABLE, strictly before it would
ever reach the 403 branch. This test proves that behavior against the real
restarting container rather than trusting the source reading alone.

A SYNTHETIC part/warehouse pair is used for the underlying transfer
proposal — never the canonical WO-42/PX-17 fixture (common.md).
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
from tests.faults.helpers import approve_if_needed, propose_transfer
from tests.integration.decision_helpers import set_inventory_and_wait

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKER_CONFIG_ENV = {
    "DOCKER_CONFIG": "/private/tmp/claude-501/-Users-d-surchis-work-operational-ontology-poc/"
    "4651d52d-5874-4c7c-ba8b-4da032dde2a5/scratchpad/docker-config"
}
# Well above the V1/V2/V3 approval_threshold_units (80/100 across versions
# seen in this repo's history) so this ALWAYS lands REQUIRES_APPROVAL
# regardless of which contract version is currently deployed.
LARGE_QTY = 500


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


def test_approve_never_403s_during_openfga_restart_warmup_window(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection,
):
    db_env.load_dotenv()

    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-975101", "WH-B", on_hand=800)
    decision = propose_transfer(decision_client, "planner-1", "WH-B", "WH-A", part, LARGE_QTY)
    assert decision["status"] == "REQUIRES_APPROVAL", (
        f"setup assumption broken: expected REQUIRES_APPROVAL for qty={LARGE_QTY}, got {decision['status']}: {decision}"
    )
    decision_id = decision["decision_id"]
    content_hash = decision["decision_content_hash"]

    stop = _docker_compose("stop", "openfga")
    if stop.returncode != 0:
        pytest.skip(f"could not stop openfga: {stop.stderr}")

    try:
        # Immediately, while openfga is down: must be 503 (F23: fail closed,
        # explicit unavailable), never a fabricated 403 "denied" the gate
        # never actually issued.
        r_down = decision_client.post(
            f"/decisions/{decision_id}/approve",
            json={"approver_id": "supervisor-1", "decision_content_hash": content_hash},
        )
        assert r_down.status_code != 403, (
            f"approve() returned 403 while OpenFGA was stopped — this is a FABRICATED denial "
            f"(F23 violation): {r_down.status_code} {r_down.text}"
        )
        assert r_down.status_code == 503, f"expected 503 while OpenFGA is down, got {r_down.status_code}: {r_down.text}"

        start = _docker_compose("start", "openfga")
        assert start.returncode == 0, f"failed to restart openfga: {start.stderr}"

        # The warm-up window itself: openfga's process health may return
        # before its store/model are fully queryable again. Poll approve()
        # (not just /healthz) through this window — every response in this
        # loop must be 503 or 200, NEVER 403, and the loop must eventually
        # reach 200 (a real, non-fabricated grant, since supervisor-1
        # legitimately has approval authority in every deployed version this
        # repo has shipped).
        deadline = time.monotonic() + 60.0
        last = None
        while time.monotonic() < deadline:
            last = decision_client.post(
                f"/decisions/{decision_id}/approve",
                json={"approver_id": "supervisor-1", "decision_content_hash": content_hash},
            )
            assert last.status_code != 403, (
                f"approve() returned 403 during the openfga warm-up window — fabricated denial "
                f"(F23 violation): {last.status_code} {last.text}"
            )
            if last.status_code == 200:
                break
            assert last.status_code in (503, 409), (
                f"unexpected status during warm-up window: {last.status_code} {last.text}"
            )
            if last.status_code == 409:
                # Already approved by a prior iteration of this same loop
                # (e.g. this call landed just after a 200 whose response we
                # didn't see due to a client-side timeout) — re-GET and stop.
                last = decision_client.get(f"/decisions/{decision_id}")
                break
            time.sleep(1.0)

        assert last is not None and last.status_code in (200, 409), (
            f"approve() never reached a real success within the warm-up window "
            f"(last: {last.status_code if last else None} {last.text if last else None}) — "
            f"an unresolved-forever state is dishonest here since supervisor-1 genuinely has authority"
        )
        final = last.json()
        assert final["status"] == "APPROVED", final
    finally:
        # Make sure openfga is left running for whatever runs next in this
        # session, regardless of pass/fail above.
        _docker_compose("start", "openfga")
        _wait_healthy(f"{db_env.openfga_api_url()}/healthz", timeout_s=60.0)
