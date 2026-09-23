"""Fake ERP FastAPI app. See services/erp/__init__.py."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from services.common.db import close_pool, get_conn, open_pool
from services.erp import db_ops
from services.erp.schemas import DelayPurchaseOrderRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    with get_conn() as conn:
        db_ops.apply_schema(conn)
    yield
    close_pool()


app = FastAPI(title="fake-erp", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "erp"}


@app.get("/suppliers")
def list_suppliers():
    with get_conn() as conn:
        return db_ops.list_suppliers(conn)


@app.get("/suppliers/{supplier_id}")
def get_supplier(supplier_id: str):
    with get_conn() as conn:
        row = db_ops.get_supplier(conn, supplier_id)
    if row is None:
        raise HTTPException(status_code=404, detail="supplier not found")
    return row


@app.get("/parts")
def list_parts():
    with get_conn() as conn:
        return db_ops.list_parts(conn)


@app.get("/parts/{part_id}")
def get_part(part_id: str):
    with get_conn() as conn:
        row = db_ops.get_part(conn, part_id)
    if row is None:
        raise HTTPException(status_code=404, detail="part not found")
    return row


@app.get("/purchase_orders")
def list_purchase_orders(status: str | None = None):
    with get_conn() as conn:
        return db_ops.list_purchase_orders(conn, status)


@app.get("/purchase_orders/{po_id}")
def get_purchase_order(po_id: str):
    with get_conn() as conn:
        row = db_ops.get_purchase_order(conn, po_id)
    if row is None:
        raise HTTPException(status_code=404, detail="purchase order not found")
    return row


@app.post("/purchase_orders/{po_id}/delay")
def delay_purchase_order(po_id: str, body: DelayPurchaseOrderRequest):
    """The supplier-delay event (docs/experiment/spec/03_domain_scenario.md)."""
    with get_conn() as conn:
        outcome, row = db_ops.delay_purchase_order(conn, po_id, body.expected_at, body.reason)
    if outcome == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="purchase order not found")
    if outcome == "TERMINAL":
        return JSONResponse(
            status_code=409,
            content={"error": "purchase order is in a terminal state", "status": row["status"]},
        )
    return row
