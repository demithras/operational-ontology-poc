"""Phase 10a step 0a: live proof that fixing the projection-rebuild
deadlock at the source (services/projection_builder/writer.py: TRUNCATE ->
DELETE FROM) actually removes the AB-BA lock-order collision, not just the
one symptom the orchestrator's `make test` run happened to hit.

Reproduction the orchestrator found (2026-09-24 17:36): psycopg
DeadlockDetected at setup of a decision_service_protected_transfer test —
a reader of work_order_risk (AccessShareLock) vs. a rebuild holding/waiting
on an AccessExclusiveLock (TRUNCATE) on the same or a downstream projection
table. services/decision_service/app.py's own `_EVIDENCE_DEADLOCK_RETRIES`
comment documents the exact AB-BA shape: evidence gathering
(services/decision_service/evidence.py::_resolve_route_protection) reads
BOTH work_order_risk and transfer_candidates in one transaction, in the
SAME order a rebuild writes them.

This test drives that exact real collision for real: one thread rebuilds
the hot projections in a tight loop (services.projection_builder.builder
.build_all — the SAME function `make rebuild-projections` and the live
poll loop both call), while 8 threads concurrently call the real
decision_service `/decisions/propose` endpoint (which reads work_order_risk
then transfer_candidates via evidence.py, exercising the identical read
path the orchestrator's deadlock came from) against a SYNTHETIC part/
warehouse pair — never the canonical WO-42/PX-17 fixture. Runs for >= 60s
(docs/experiment/briefs/phase10a.md step 0a's own bound). Asserts zero
DeadlockDetected and zero unexpected errors from either side.

Requires the real stack (`make up`, ideally `make seed`) — self-skips
otherwise, per this repo's honesty convention (never a silent pass).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import httpx
import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.projection_builder.builder import build_all  # noqa: E402

RUN_SECONDS = 60.0
N_PROPOSERS = 8
SYNTHETIC_PART = "SKU-975001"  # never used by seed/generators/generate.py (100000-100499) or PX-17/88429


def _rebuild_loop(stop_at: float, errors: list[BaseException], iterations: list[int]) -> None:
    db_env.load_dotenv()
    client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    try:
        while time.monotonic() < stop_at:
            try:
                with psycopg.connect(db_env.ontology_hot_dsn()) as conn:
                    build_all(client, conn)
                iterations[0] += 1
            except BaseException as exc:  # noqa: BLE001 - record every failure, classify after
                errors.append(exc)
    finally:
        client.close()


def _proposer_loop(
    decision_url: str, stop_at: float, errors: list[BaseException], attempts: list[int], worker_id: int
) -> None:
    with httpx.Client(base_url=decision_url, timeout=httpx.Timeout(15.0)) as client:
        n = 0
        while time.monotonic() < stop_at:
            n += 1
            try:
                r = client.post(
                    "/decisions/propose",
                    json={
                        "action_type": "transfer_inventory",
                        "actor": {"type": "user", "id": "planner-1"},
                        "parameters": {
                            "source_warehouse": "WH-A",
                            "destination_warehouse": "WH-B",
                            "part": SYNTHETIC_PART,
                            "quantity": 1 + (worker_id % 5),
                        },
                        "context": {},
                    },
                )
                # 503 (dependency/gate unavailable under load) and 200/409 are
                # all acceptable HTTP-level outcomes here — this test is about
                # the absence of a Postgres deadlock, not about the decision
                # outcome for a made-up part with no real evidence behind it.
                # Anything else (esp. a raw connection error bubbling up as an
                # httpx exception, or a 500) is recorded as unexpected.
                if r.status_code not in (200, 404, 409, 422, 503):
                    errors.append(AssertionError(f"worker {worker_id}: unexpected status {r.status_code}: {r.text[:300]}"))
            except httpx.HTTPError as exc:
                errors.append(exc)
        attempts[0] = n


def test_rebuild_loop_and_concurrent_proposers_never_deadlock(stack_up: bool):
    if not stack_up:
        pytest.skip("stack not reachable — run 'make up' first")

    decision_url = db_env.decision_service_url()
    if not _decision_service_reachable(decision_url):
        pytest.skip(f"decision_service not reachable at {decision_url} — run 'make up' first")

    stop_at = time.monotonic() + RUN_SECONDS

    rebuild_errors: list[BaseException] = []
    rebuild_iterations = [0]
    rebuild_thread = threading.Thread(
        target=_rebuild_loop, args=(stop_at, rebuild_errors, rebuild_iterations), daemon=True
    )

    proposer_errors: list[BaseException] = []
    proposer_attempts: list[list[int]] = [[0] for _ in range(N_PROPOSERS)]
    proposer_threads = [
        threading.Thread(
            target=_proposer_loop,
            args=(decision_url, stop_at, proposer_errors, proposer_attempts[i], i),
            daemon=True,
        )
        for i in range(N_PROPOSERS)
    ]

    rebuild_thread.start()
    for t in proposer_threads:
        t.start()

    rebuild_thread.join(timeout=RUN_SECONDS + 30)
    for t in proposer_threads:
        t.join(timeout=RUN_SECONDS + 30)

    total_proposer_attempts = sum(a[0] for a in proposer_attempts)
    deadlocks = [e for e in rebuild_errors + proposer_errors if isinstance(e, psycopg.errors.DeadlockDetected)]

    assert rebuild_iterations[0] > 0, "rebuild loop never completed a single cycle — test setup is broken, not a pass"
    assert total_proposer_attempts >= N_PROPOSERS, "proposer threads never issued a single request — test setup is broken"
    assert deadlocks == [], f"{len(deadlocks)} DeadlockDetected during {RUN_SECONDS}s of concurrent rebuild + propose: {deadlocks[:3]}"
    other_errors = [e for e in rebuild_errors + proposer_errors if not isinstance(e, psycopg.errors.DeadlockDetected)]
    assert other_errors == [], f"{len(other_errors)} unexpected errors (non-deadlock) during the run: {other_errors[:5]}"


def _decision_service_reachable(base_url: str) -> bool:
    try:
        r = httpx.get(f"{base_url}/health", timeout=2.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False
