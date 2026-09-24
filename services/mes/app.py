"""Fake MES FastAPI app. See services/mes/__init__.py."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from services.common.db import close_pool, get_conn, open_pool
from services.mes import db_ops
from services.mes.schemas import RescheduleWorkOrderRequest


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
