"""Fake WMS FastAPI app. See services/wms/__init__.py."""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from services.common.db import close_pool, get_conn, open_pool
from services.common.faults import registry
from services.wms import db_ops, transfers
from services.wms.schemas import (
    ArmFaultRequest,
    IdempotencyCheckRequest,
    ReverseTransferRequest,
    SetInventoryRequest,
    TransferRequest,
)

TEST_MODE = os.environ.get("OO_TEST_MODE") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_pool()
    with get_conn() as conn:
        db_ops.apply_schema(conn)
    yield
    close_pool()


app = FastAPI(title="fake-wms", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": "wms", "test_mode": TEST_MODE}


@app.get("/warehouses")
def list_warehouses():
    with get_conn() as conn:
        return db_ops.list_warehouses(conn)


@app.get("/warehouses/{warehouse_id}")
def get_warehouse(warehouse_id: str):
    with get_conn() as conn:
        row = db_ops.get_warehouse(conn, warehouse_id)
    if row is None:
        raise HTTPException(status_code=404, detail="warehouse not found")
    return row


@app.get("/inventory_lots")
def list_inventory_lots(part: str | None = None, warehouse_id: str | None = None):
    with get_conn() as conn:
        return db_ops.list_inventory_lots(conn, part=part, warehouse_id=warehouse_id)


@app.get("/inventory_lots/{lot_id}")
def get_inventory_lot(lot_id: str):
    with get_conn() as conn:
        row = db_ops.get_inventory_lot(conn, lot_id)
    if row is None:
        raise HTTPException(status_code=404, detail="inventory lot not found")
    return row


@app.post("/transfers")
def create_transfer(body: TransferRequest):
    with get_conn() as conn:
        status, payload = transfers.create_transfer(
            conn,
            action_execution_id=body.action_execution_id,
            source_warehouse=body.source,
            destination_warehouse=body.destination,
            part=body.part,
            quantity=body.quantity,
            test_mode=TEST_MODE,
        )
    return JSONResponse(status_code=status, content=jsonable_encoder(payload))


@app.get("/transfers/{action_execution_id}")
def get_transfer(action_execution_id: str):
    with get_conn() as conn:
        row = db_ops.get_transfer(conn, action_execution_id)
    if row is None:
        raise HTTPException(status_code=404, detail="transfer not found")
    return row


@app.post("/transfers/{action_execution_id}/reverse")
def reverse_transfer(action_execution_id: str, body: ReverseTransferRequest):
    reversal_id = body.action_execution_id or f"{action_execution_id}-reverse-{uuid.uuid4().hex[:8]}"
    with get_conn() as conn:
        status, payload = transfers.reverse_transfer(
            conn,
            original_action_execution_id=action_execution_id,
            reversal_action_execution_id=reversal_id,
            test_mode=TEST_MODE,
        )
    return JSONResponse(status_code=status, content=jsonable_encoder(payload))


if TEST_MODE:

    @app.post("/_test/faults/arm")
    def arm_fault(body: ArmFaultRequest):
        registry.arm(
            mode=body.mode,
            scope=body.scope,
            n=body.n,
            action_execution_id=body.action_execution_id,
            params=body.params,
        )
        return {"armed": True, "snapshot": registry.snapshot()}

    @app.post("/_test/faults/reset")
    def reset_faults():
        registry.reset()
        return {"reset": True}

    @app.get("/_test/faults")
    def get_faults():
        return registry.snapshot()

    @app.post("/_test/idempotency-check")
    def set_idempotency_check(body: IdempotencyCheckRequest):
        """Phase 10a item 1: process-wide toggle, distinct from the
        per-action_execution_id fault registry above — see
        services/common/faults.py::FaultRegistry's docstring for why a
        separate mechanism is needed to model "idempotency itself is
        broken" rather than "the first attempt misbehaves"."""
        if body.enabled:
            registry.enable_idempotency_check()
        else:
            registry.disable_idempotency_check()
        return {"idempotency_check_enabled": registry.idempotency_check_enabled()}

    @app.post("/_test/inventory/set")
    def set_inventory(body: SetInventoryRequest):
        """Exact upsert of one inventory lot, so concurrency/race tests can
        set up a known stock level without depending on seeded data or test
        execution order (docs/experiment/spec/09_failure_and_adversarial_matrix.md
        "Concurrency tests")."""
        with get_conn() as conn:
            row = db_ops.set_inventory_for_test(
                conn, body.part, body.warehouse_id, body.on_hand, body.reserved, body.quality_status
            )
        return row
