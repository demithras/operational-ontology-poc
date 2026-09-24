"""Baseline decision service FastAPI app (Phase 8, spec 10 Variant A) —
same API surface as services/decision_service/app.py (propose/get/approve/
execute/executions/outcomes/replay/reevaluate), host port 15411. Thin HTTP
wiring; services/baseline/propose_flow.py does the real orchestration.
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

from services.baseline import execution, execution_reader, store
from services.baseline.config import from_env
from services.baseline.manifest import build_baseline_manifest
from services.baseline.models import APPROVED, GATE_UNAVAILABLE, REQUIRES_APPROVAL
from services.baseline.propose_flow import MalformedProposal, ProposeDeps, propose
from services.common.db import close_pool, get_conn, open_pool
from services.decision_service import authz
from services.decision_service.action_types import get_action_type
from services.decision_service.schemas import ApproveRequest, ProposeRequest

TEST_MODE = os.environ.get("OO_TEST_MODE") == "1"
_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = from_env()
    open_pool()
    with get_conn() as conn:
        store.apply_schema(conn)
    http_clients = {
        "wms": httpx.Client(base_url=config.wms_base_url, timeout=5.0),
        "erp": httpx.Client(base_url=config.erp_base_url, timeout=5.0),
        "mes": httpx.Client(base_url=config.mes_base_url, timeout=5.0),
    }
    temporal_client = None
    for _attempt in range(10):
        try:
            temporal_client = await TemporalClient.connect(config.temporal_address, namespace="default")
            break
        except Exception:  # noqa: BLE001
            await asyncio.sleep(2.0)

    _state.update(config=config, http_clients=http_clients, temporal_client=temporal_client)
    yield
    for c in http_clients.values():
        c.close()
    close_pool()


app = FastAPI(title="baseline-decision-service", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "baseline", "openfga_store_id": _current_store_id()}


def _current_store_id() -> str | None:
    return authz.resolve_store_id(_state["config"].openfga_api_url)


def _deps(conn) -> ProposeDeps:
    config = _state["config"]
    store_id = _current_store_id()
    model_id = authz.resolve_latest_authorization_model_id(config.openfga_api_url, store_id) if store_id else None
    return ProposeDeps(
        conn=conn, http_clients=_state["http_clients"], openfga_api_url=config.openfga_api_url,
        openfga_store_id=store_id, opa_base_url=config.opa_base_url,
        manifest=build_baseline_manifest(), openfga_authorization_model_id=model_id,
    )


def _decision_response(row: dict) -> dict:
    return jsonable_encoder(row, exclude_none=False)


_EVIDENCE_DEADLOCK_RETRIES = 3


@app.post("/decisions/propose")
def decisions_propose(body: ProposeRequest):
    for attempt in range(_EVIDENCE_DEADLOCK_RETRIES):
        with get_conn() as conn:
            try:
                record = propose(_deps(conn), body.actor.type, body.actor.id, body.action_type, body.parameters, body.context)
            except MalformedProposal as exc:
                store.record_proposal_attempt_failure(conn, body.action_type, body.actor.type, body.actor.id, "malformed_proposal", str(exc))
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except psycopg.errors.DeadlockDetected as exc:
                conn.rollback()
                if attempt < _EVIDENCE_DEADLOCK_RETRIES - 1:
                    continue
                store.record_proposal_attempt_failure(conn, body.action_type, body.actor.type, body.actor.id, "dependency_unavailable", str(exc))
                raise HTTPException(status_code=503, detail=f"baseline dependency unavailable (deadlock retries exhausted): {exc}") from exc
            except (httpx.HTTPError, ConnectionError, psycopg.Error) as exc:
                conn.rollback()
                store.record_proposal_attempt_failure(conn, body.action_type, body.actor.type, body.actor.id, "dependency_unavailable", str(exc))
                raise HTTPException(status_code=503, detail=f"baseline dependency unavailable: {exc}") from exc
            row = store.get_decision(conn, record.decision_id)
        status_code = 503 if row["status"] == GATE_UNAVAILABLE else 200
        return JSONResponse(status_code=status_code, content=_decision_response(row))
    raise AssertionError("unreachable")


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
            raise HTTPException(status_code=409, detail="decision_content_hash mismatch — the decision has changed since this approval was prepared (F33)")
        action = get_action_type(row["action_type"], row.get("action_version_dir") or "v1")
        object_ref = (row.get("authorization_result") or {}).get("object_or_input_hash")
        if action is None or object_ref is None:
            raise HTTPException(status_code=409, detail="cannot approve: no recorded authorization object")

        store_id = _current_store_id()
        if store_id is None:
            raise HTTPException(status_code=503, detail="OpenFGA unavailable — cannot verify approval authority (F23)")
        approve_check = authz.check(_state["config"].openfga_api_url, store_id, action.approval_relation, object_ref, "user", body.approver_id)
        if not approve_check.allowed:
            if approve_check.outcome == authz.UNAVAILABLE:
                raise HTTPException(status_code=503, detail=f"OpenFGA did not answer the approval-authority check for {object_ref!r} (F23): {approve_check.detail}")
            raise HTTPException(status_code=403, detail=f"approver {body.approver_id!r} lacks {action.approval_relation!r} on {object_ref!r} (outcome={approve_check.outcome})")

        approved_at = datetime.now(timezone.utc)
        store.update_approval(conn, decision_id, body.approver_id, approved_at, body.decision_content_hash, body.scope, APPROVED)
        row = store.get_decision(conn, decision_id)
    return _decision_response(row)


@app.post("/decisions/{decision_id}/execute")
async def decisions_execute(decision_id: str):
    with get_conn() as conn:
        row = store.get_decision(conn, decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="decision not found")
    if row["status"] not in (APPROVED, "EXECUTING", "OBSERVED_SUCCESS", "DIVERGED", "OUTCOME_UNKNOWN", "EXECUTION_FAILED"):
        raise HTTPException(status_code=409, detail=f"decision is not APPROVED and never executed (status={row['status']})")

    temporal_client = _state.get("temporal_client")
    if temporal_client is None:
        raise HTTPException(status_code=503, detail="Temporal is unavailable — decision remains APPROVED and unexecuted (F25)")

    action_execution_id = execution.action_execution_id_for(decision_id)
    try:
        handle, started_now = await execution.start_or_get_execution(temporal_client, decision_id)
    except RPCError as exc:
        raise HTTPException(status_code=503, detail=f"Temporal unavailable — decision remains APPROVED and unexecuted (F25): {exc}") from exc

    return JSONResponse(
        status_code=202,
        content={
            "decision_id": decision_id, "action_execution_id": action_execution_id, "temporal_workflow_id": handle.id,
            "started_now": started_now, "decision_content_hash": row["decision_content_hash"],
        },
    )


@app.get("/executions/{execution_id}")
def executions_get(execution_id: str):
    with get_conn() as conn:
        row = execution_reader.get_execution(conn, execution_id)
    if row is None:
        raise HTTPException(status_code=404, detail="execution not found")
    return row


@app.get("/outcomes/{outcome_id}")
def outcomes_get(outcome_id: str):
    with get_conn() as conn:
        row = execution_reader.get_outcome(conn, outcome_id)
    if row is None:
        raise HTTPException(status_code=404, detail="outcome not found")
    return row


@app.post("/replay/{decision_id}")
def replay(decision_id: str):
    from services.baseline import replay as replay_mod
    from services.decision_service.replay import ReplayIntegrityError

    with get_conn() as conn:
        try:
            result = replay_mod.replay_decision(decision_id, conn, _state["config"].openfga_api_url, _state["config"].opa_base_url)
        except replay_mod.DecisionNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ReplayIntegrityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.as_dict()
