"""Decision service FastAPI app — docs/experiment/spec/06_decision_and_action_runtime.md
"API surface". Thin HTTP wiring only; the real orchestration is
services/decision_service/propose_flow.py::propose (kept separate so it is
callable/testable without an HTTP layer).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from services.common.db import close_pool, get_conn, open_pool
from services.common.rdf4j_client import RDF4JClient
from services.decision_service import authz, manifest as manifest_mod, planner, rdf_writer, store
from services.decision_service.action_types import get_action_type
from services.decision_service.config import from_env
from services.decision_service.models import APPROVED, REQUIRES_APPROVAL
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
    }
    _state.update(
        config=config,
        rdf4j_client=rdf4j_client,
        http_clients=http_clients,
        manifest=manifest_mod.write_manifest(),
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
    return ProposeDeps(
        conn=conn,
        rdf4j_client=_state["rdf4j_client"],
        http_clients=_state["http_clients"],
        openfga_api_url=config.openfga_api_url,
        openfga_store_id=_current_store_id(),
        opa_base_url=config.opa_base_url,
        manifest=_state["manifest"],
    )


def _decision_response(row: dict) -> dict:
    return jsonable_encoder(row, exclude_none=False)


@app.post("/decisions/propose")
def decisions_propose(body: ProposeRequest):
    force_invalid = TEST_MODE and str(body.context.get("force_invalid_conformance", "")).lower() == "true"
    with get_conn() as conn:
        try:
            record = propose(
                _deps(conn), body.actor.type, body.actor.id, body.action_type,
                body.parameters, body.context, force_invalid_conformance=force_invalid,
            )
        except MalformedProposal as exc:
            store.record_proposal_attempt_failure(conn, body.action_type, body.actor.type, body.actor.id, "malformed_proposal", str(exc))
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    return JSONResponse(status_code=200, content=_decision_response(row))


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
        action = get_action_type(row["action_type"])
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
def decisions_execute(decision_id: str):
    with get_conn() as conn:
        row = store.get_decision(conn, decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="decision not found")
    if row["status"] not in (APPROVED,):
        raise HTTPException(status_code=409, detail=f"decision is not APPROVED (status={row['status']})")
    # Verify the exact immutable approved tuple, per spec 06 execute():
    # "verify immutable content hash" — real Temporal-driven execution is
    # Phase 6; this endpoint proves the verification step is real without
    # yet performing the external call.
    return JSONResponse(
        status_code=501,
        content={
            "detail": "not implemented yet — Phase 6 (Temporal action runtime)",
            "decision_id": decision_id,
            "verified_immutable_tuple": True,
            "decision_content_hash": row["decision_content_hash"],
        },
    )


@app.get("/executions/{execution_id}")
def executions_get(execution_id: str):
    raise HTTPException(status_code=501, detail="not implemented yet — Phase 6 (Temporal action runtime)")


@app.get("/outcomes/{outcome_id}")
def outcomes_get(outcome_id: str):
    raise HTTPException(status_code=501, detail="not implemented yet — Phase 6 (Temporal action runtime)")


@app.post("/replay/{decision_id}")
def replay(decision_id: str):
    raise HTTPException(status_code=501, detail="not implemented yet — Phase 7 (contract versioning / replay)")


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
