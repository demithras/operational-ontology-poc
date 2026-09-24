"""Fake MES FastAPI app. See services/mes/__init__.py."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from services.common.db import close_pool, get_conn, open_pool
from services.mes import db_ops
from services.mes.schemas import RescheduleWorkOrderRequest, SetWorkOrderRequest

TEST_MODE = os.environ.get("OO_TEST_MODE") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    with get_conn() as conn:
        db_ops.apply_schema(conn)
    yield
    close_pool()


app = FastAPI(title="fake-mes", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "mes"}


@app.get("/production_lines")
def list_production_lines():
    with get_conn() as conn:
        return db_ops.list_production_lines(conn)


@app.get("/production_lines/{line_id}")
def get_production_line(line_id: str):
    with get_conn() as conn:
        row = db_ops.get_production_line(conn, line_id)
    if row is None:
        raise HTTPException(status_code=404, detail="production line not found")
    return row


@app.get("/work_orders")
def list_work_orders(status: str | None = None):
    with get_conn() as conn:
        return db_ops.list_work_orders(conn, status)


@app.get("/work_orders/{work_order_id}")
def get_work_order(work_order_id: str):
    with get_conn() as conn:
        row = db_ops.get_work_order(conn, work_order_id)
    if row is None:
        raise HTTPException(status_code=404, detail="work order not found")
    return row


@app.post("/work_orders/{work_order_id}/reschedule")
def reschedule_work_order(work_order_id: str, body: RescheduleWorkOrderRequest):
    with get_conn() as conn:
        if body.action_execution_id is None:
            # Pre-Phase-6 path, unchanged — no idempotency key, always applies.
            outcome, row = db_ops.reschedule_work_order(conn, work_order_id, body.new_planned_start)
        else:
            outcome, row = db_ops.reschedule_work_order_with_idempotency(
                conn, work_order_id, body.action_execution_id, body.new_planned_start
            )
    if outcome == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="work order not found")
    if outcome == "TERMINAL":
        return JSONResponse(
            status_code=409,
            content={"error": "cannot reschedule a DONE/CANCELLED work order", "status": row["status"]},
        )
    if outcome == "CONFLICT":
        return JSONResponse(
            status_code=409,
            content={"error": "action_execution_id already used with a different request body", "action_execution_id": body.action_execution_id},
        )
    if outcome == "REPLAYED":
        return JSONResponse(status_code=200, content=jsonable_encoder({**row, "replayed": True}))
    return row


if TEST_MODE:

    @app.post("/_test/work_orders/{work_order_id}")
    def set_work_order(work_order_id: str, body: SetWorkOrderRequest):
        """Phase 10 fix (docs/experiment/briefs/phase10fix.md "self-contained
        fixtures"): exact upsert of one synthetic HIGH/MEDIUM/LOW-priority
        work order plus its full BOM requirement set, so integration tests
        can build their own at-risk-work-order precondition instead of
        scavenging whichever real seeded work order happens to currently
        qualify. Same TEST_MODE-gated convention as
        services/wms/app.py::set_inventory."""
        with get_conn() as conn:
            row = db_ops.set_work_order_for_test(
                conn,
                work_order_id,
                priority=body.priority,
                warehouse=body.warehouse,
                requirements=[r.model_dump() for r in body.requirements],
                status=body.status,
                planned_start=body.planned_start,
                planned_finish=body.planned_finish,
                production_line_id=body.production_line_id,
            )
        return jsonable_encoder(row)
