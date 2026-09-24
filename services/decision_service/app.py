"""Decision service FastAPI app — docs/experiment/spec/06_decision_and_action_runtime.md
"API surface". Thin HTTP wiring only; the real orchestration is
services/decision_service/propose_flow.py::propose (kept separate so it is
callable/testable without an HTTP layer).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError

from services.common.db import close_pool, get_conn, open_pool
from services.common.rdf4j_client import RDF4JClient
from services.decision_service import authz, execution, execution_reader, manifest as manifest_mod, planner, rdf_writer, store
from services.decision_service.action_types import get_action_type
from services.decision_service.config import from_env
from services.decision_service.models import APPROVED, GATE_UNAVAILABLE, REQUIRES_APPROVAL
from services.decision_service.propose_flow import MalformedProposal, ProposeDeps, propose
from services.decision_service.schemas import ApproveRequest, ProposeRequest

TEST_MODE = os.environ.get("OO_TEST_MODE") == "1"

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = from_env()
    open_pool()
    with get_conn() as conn:
        store.apply_schema(conn)
    rdf4j_client = RDF4JClient(base_url=config.rdf4j_base_url, repository=config.rdf4j_repository)
    http_clients = {
        "wms": httpx.Client(base_url=config.wms_base_url, timeout=5.0),
        "erp": httpx.Client(base_url=config.erp_base_url, timeout=5.0),
        "mes": httpx.Client(base_url=config.mes_base_url, timeout=5.0),
        # Phase 5 fix (watermark-based evidence freshness): the per-source
        # "verified_through" watermark ingestion tracks (real CDC events +
        # Debezium heartbeats) — see evidence.py::_resolve_source_inventory_with_freshness.
        "ingestion": httpx.Client(base_url=config.ingestion_health_url, timeout=5.0),
    }
    # Phase 6: connect lazily-tolerant — F25 ("Temporal unavailable ->
    # execution -> approved decision remains unexecuted, auditable") must
    # not make decision_service itself fail to START just because Temporal
    # isn't up yet; `execute()` below checks `_state["temporal_client"]`
    # itself and returns 503 rather than crashing. `Client.connect` does
    # perform a real handshake, so this is retried a few times before
    # giving up for this process's lifetime (a subsequent `make up` restart
    # re-attempts).
    temporal_client = None
    for _attempt in range(10):
        try:
            temporal_client = await TemporalClient.connect(config.temporal_address, namespace="default")
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(2.0)

    _state.update(
        config=config,
        rdf4j_client=rdf4j_client,
        http_clients=http_clients,
        manifest=manifest_mod.write_manifest(),
        temporal_client=temporal_client,
    )
    yield
    rdf4j_client.close()
    for c in http_clients.values():
        c.close()
    close_pool()


app = FastAPI(title="decision-service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "decision_service", "openfga_store_id": _current_store_id()}


def _current_store_id() -> str | None:
    # Deliberately NOT cached across requests. Two real races demand this:
    # (1) `make up` brings decision_service up BEFORE running
    #     services/decision_service/bootstrap_openfga.py, so the store may
    #     not exist yet at THIS container's own startup;
    # (2) OpenFGA runs with the `memory` datastore engine (docker-compose.yml)
    #     — a later OpenFGA container restart (e.g. an F23 outage test, or a
    #     real operational restart) wipes its store entirely, and
    #     bootstrap_openfga.py creates a BRAND NEW store id when it re-runs.
    #     A cached old id would then silently and PERMANENTLY 404 forever
    #     (found empirically: an F23 outage test followed by an F24 test in
    #     the same container lifetime got DENIED_AUTHORIZATION instead of
    #     reaching the policy gate, because the cached store id no longer
    #     existed). Re-resolving is one cheap local GET /stores call —
    #     negligible next to the authz.check() call that follows it, and
    #     keeps this self-healing without needing a decision_service restart.
    return authz.resolve_store_id(_state["config"].openfga_api_url)


def _deps(conn) -> ProposeDeps:
    config = _state["config"]
    store_id = _current_store_id()
    model_id = authz.resolve_latest_authorization_model_id(config.openfga_api_url, store_id) if store_id else None
    return ProposeDeps(
        conn=conn,
        rdf4j_client=_state["rdf4j_client"],
        http_clients=_state["http_clients"],
        openfga_api_url=config.openfga_api_url,
        openfga_store_id=store_id,
        opa_base_url=config.opa_base_url,
        # Phase 7: manifest re-read fresh per request (never the stale
        # startup-time _state["manifest"]) so a contract redeploy (an edit
        # to contracts/manifests/deployed_version.json) takes effect on the
        # very next propose() with no decision_service restart — the same
        # "read live state, don't trust a process-lifetime cache" policy
        # _current_store_id() already established for OpenFGA.
        manifest=manifest_mod.build_manifest(),
        openfga_authorization_model_id=model_id,
    )


def _decision_response(row: dict) -> dict:
    return jsonable_encoder(row, exclude_none=False)


_EVIDENCE_DEADLOCK_RETRIES = 3


@app.post("/decisions/propose")
def decisions_propose(body: ProposeRequest):
    force_invalid = TEST_MODE and str(body.context.get("force_invalid_conformance", "")).lower() == "true"
    for attempt in range(_EVIDENCE_DEADLOCK_RETRIES):
        with get_conn() as conn:
            try:
                record = propose(
                    _deps(conn), body.actor.type, body.actor.id, body.action_type,
                    body.parameters, body.context, force_invalid_conformance=force_invalid,
                )
            except MalformedProposal as exc:
                store.record_proposal_attempt_failure(conn, body.action_type, body.actor.type, body.actor.id, "malformed_proposal", str(exc))
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except psycopg.errors.DeadlockDetected as exc:
                # Phase 6: evidence-gathering now reads BOTH work_order_risk
                # AND transfer_candidates in the SAME transaction
                # (services/decision_service/evidence.py::_resolve_route_protection)
                # — a real, reproducible AB-BA lock-order collision against
                # services/projection_builder's own TRUNCATE order
                # (work_order_risk -> transfer_candidates, one poll-interval
                # transaction) whenever the two overlap AND a route actually
                # matches a candidate. This is Postgres's OWN self-defense
                # (one of the two transactions is always aborted to break
                # the cycle) — a read-only evidence-gathering retry with a
                # FRESH connection is always safe (no write has happened
                # yet; conn is already aborted, so the retry re-enters
                # `get_conn()` rather than reusing it).
                conn.rollback()
                if attempt < _EVIDENCE_DEADLOCK_RETRIES - 1:
                    continue
                store.record_proposal_attempt_failure(conn, body.action_type, body.actor.type, body.actor.id, "dependency_unavailable", str(exc))
                raise HTTPException(status_code=503, detail=f"decision service dependency unavailable (deadlock retries exhausted): {exc}") from exc
            except (httpx.HTTPError, ConnectionError, psycopg.Error) as exc:
                # F22: RDF4J/dependency unreachable before a Decision could even
                # be attempted -> explicit failure, never a fabricated status.
                # rollback() first: a psycopg.Error leaves the connection's own
                # transaction aborted, and the INSERT below would itself fail
                # ("current transaction is aborted") without this.
                conn.rollback()
                store.record_proposal_attempt_failure(conn, body.action_type, body.actor.type, body.actor.id, "dependency_unavailable", str(exc))
                raise HTTPException(status_code=503, detail=f"decision service dependency unavailable: {exc}") from exc
            row = store.get_decision(conn, record.decision_id)
        # Phase 8 step 0 (acceptance criterion A.11): a governed Decision WAS
        # written (unlike the F22 RDF4J-unreachable branches above, which
        # 503 with NO decision at all) — but a required gate never
        # answered, so the API itself must surface that as an explicit
        # failure (503), never a fabricated-looking 200. The full record
        # (status=GATE_UNAVAILABLE, unavailable_gate, decision_id) is still
        # returned in the body so the caller can look it up / retry
        # propose() once the dependency recovers.
        status_code = 503 if row["status"] == GATE_UNAVAILABLE else 200
        return JSONResponse(status_code=status_code, content=_decision_response(row))
    raise AssertionError("unreachable")  # loop always returns or raises


@app.get("/decisions/{decision_id}")
def decisions_get(decision_id: str):
    with get_conn() as conn:
        row = store.get_decision(conn, decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return _decision_response(row)


@app.post("/decisions/{decision_id}/approve")
def decisions_approve(decision_id: str, body: ApproveRequest):
    with get_conn() as conn:
        row = store.get_decision(conn, decision_id)
        if row is None:
            raise HTTPException(status_code=404, detail="decision not found")
        if row["status"] != REQUIRES_APPROVAL:
            raise HTTPException(status_code=409, detail=f"decision is not awaiting approval (status={row['status']})")
        if row["decision_content_hash"] != body.decision_content_hash:
            # F33: approval replay on a changed decision -> rejected.
            raise HTTPException(
                status_code=409,
                detail="decision_content_hash mismatch — the decision has changed since this approval was prepared (F33)",
            )
        action = get_action_type(row["action_type"], row.get("action_version_dir") or "v1")
        object_ref = (row.get("authorization_result") or {}).get("object")
        if action is None or object_ref is None:
            raise HTTPException(status_code=409, detail="cannot approve: no recorded authorization object")

        store_id = _current_store_id()
        if store_id is None:
            raise HTTPException(status_code=503, detail="OpenFGA unavailable — cannot verify approval authority (F23)")
        approve_check = authz.check(
            _state["config"].openfga_api_url, store_id, action.approval_relation, object_ref, "user", body.approver_id,
        )
        if not approve_check.allowed:
            if approve_check.outcome == authz.UNAVAILABLE:
                # Phase 8 step 0: the gate never answered (transient OpenFGA
                # warm-up/outage after store_id itself resolved) — this is
                # NOT the same as the approver genuinely lacking authority.
                # 503 (gate unavailable), never a fabricated 403 denial the
                # gate never actually issued (acceptance criterion A.11).
                raise HTTPException(
                    status_code=503,
                    detail=f"OpenFGA did not answer the approval-authority check for {object_ref!r} (F23): {approve_check.detail}",
                )
            raise HTTPException(
                status_code=403,
                detail=f"approver {body.approver_id!r} lacks {action.approval_relation!r} on {object_ref!r} (outcome={approve_check.outcome})",
            )

        approved_at = datetime.now(timezone.utc)
        committed, detail = rdf_writer.record_approval(
            _state["rdf4j_client"], decision_id, body.approver_id, approved_at, body.decision_content_hash, body.scope,
        )
        if not committed:
            raise HTTPException(status_code=409, detail=f"approval rejected by SHACL: {detail[:500]}")

        store.update_approval(conn, decision_id, body.approver_id, approved_at, body.decision_content_hash, body.scope, APPROVED)
        row = store.get_decision(conn, decision_id)
    return _decision_response(row)


@app.post("/decisions/{decision_id}/execute")
async def decisions_execute(decision_id: str):
    with get_conn() as conn:
        row = store.get_decision(conn, decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="decision not found")
    # A decision already past APPROVED (EXECUTING or any terminal execution
    # status) is not an error — execute() is idempotent per decision
    # (F10/F25): re-resolve the SAME workflow rather than 409ing, so a
    # caller retrying a slow/uncertain first call gets the real status back.
    if row["status"] not in (APPROVED, "EXECUTING", "OBSERVED_SUCCESS", "DIVERGED", "OUTCOME_UNKNOWN", "EXECUTION_FAILED"):
        raise HTTPException(status_code=409, detail=f"decision is not APPROVED and never executed (status={row['status']})")

    temporal_client = _state.get("temporal_client")
    if temporal_client is None:
        # F25: "Temporal unavailable -> approved decision remains
        # unexecuted, auditable" — a clear, explicit 503, never a decision
        # silently left in a fabricated-looking state.
        raise HTTPException(status_code=503, detail="Temporal is unavailable — decision remains APPROVED and unexecuted (F25)")

    action_execution_id = execution.action_execution_id_for(decision_id)
    try:
        handle, started_now = await execution.start_or_get_execution(temporal_client, decision_id)
    except RPCError as exc:
        raise HTTPException(status_code=503, detail=f"Temporal unavailable — decision remains APPROVED and unexecuted (F25): {exc}") from exc

    return JSONResponse(
        status_code=202,
        content={
            "decision_id": decision_id,
            "action_execution_id": action_execution_id,
            "temporal_workflow_id": handle.id,
            "started_now": started_now,
            "verified_immutable_tuple": True,
            "decision_content_hash": row["decision_content_hash"],
        },
    )


@app.get("/executions/{execution_id}")
def executions_get(execution_id: str):
    row = execution_reader.get_execution(_state["rdf4j_client"], execution_id)
    if row is None:
        raise HTTPException(status_code=404, detail="execution not found")
    return row


@app.get("/outcomes/{outcome_id}")
def outcomes_get(outcome_id: str):
    row = execution_reader.get_outcome(_state["rdf4j_client"], outcome_id)
    if row is None:
        raise HTTPException(status_code=404, detail="outcome not found")
    return row


@app.post("/replay/{decision_id}")
def replay(decision_id: str):
    from services.decision_service import replay as replay_mod

    with get_conn() as conn:
        try:
            result = replay_mod.replay_decision(
                decision_id, conn, _state["rdf4j_client"], _state["config"].openfga_api_url,
                _state["config"].opa_base_url,
            )
        except replay_mod.DecisionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except replay_mod.ReplayIntegrityError as exc:
            # F29: "old policy deleted -> replay fails loudly" — a real
            # error status, never a silently-degraded 200.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.as_dict()


@app.post("/reevaluate/{decision_id}")
def reevaluate(decision_id: str):
    from services.decision_service import replay as replay_mod

    with get_conn() as conn:
        try:
            result = replay_mod.reevaluate_under_current(decision_id, conn, _state["config"].opa_base_url)
        except replay_mod.DecisionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


if TEST_MODE:

    @app.get("/_test/recommend_transfer/{work_order_id}")
    def test_recommend_transfer(work_order_id: str):
        """Test-mode-only wiring for services/decision_service/planner.py
        (H10 deterministic planner) — lets integration tests exercise
        "planner recommends -> submit to propose()" end to end without a
        separate CLI."""
        with get_conn() as conn:
            recommendation = planner.recommend_transfer_for_work_order(conn, work_order_id)
        if recommendation is None:
            raise HTTPException(status_code=404, detail="no at-risk work order / candidate found")
        return recommendation
