"""Action-level logic: preconditions, outcome predicates and effect payloads (bound by IR text / "<action>#<i>")."""
from __future__ import annotations

from . import data, facts


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def pre_quantity(ctx) -> bool:
    return _int(ctx.inputs["quantity"]) and ctx.inputs["quantity"] >= 1


def pre_distinct(ctx) -> bool:
    return ctx.inputs["source_warehouse"] != ctx.inputs["destination_warehouse"]


def pre_source_available(ctx) -> bool:
    i = ctx.inputs
    lot = facts.lot_for(ctx.view, i["part"], i["source_warehouse"])
    return lot is not None and facts.available(lot) >= i["quantity"]


def pre_fee(ctx) -> bool:
    return _int(ctx.inputs["expedite_fee"]) and ctx.inputs["expedite_fee"] >= 0


def pre_po_open(ctx) -> bool:
    po = ctx.view.get("PurchaseOrder", ctx.inputs["po_id"])
    return po is not None and po["props"].get("status") not in data.TERMINAL_PO


def pre_wo_open(ctx) -> bool:
    wo = ctx.view.get("WorkOrder", ctx.inputs["work_order_id"])
    return wo is not None and wo["props"].get("status") not in data.TERMINAL_WO


def _records(ctx, obs_type: str) -> list[dict]:
    return [o["data"] for o in ctx.observations if o.get("observation_type") == obs_type]


def outcome_transfer(ctx):
    """Reconciliation v1 transfer_inventory rules (contracts/reconciliation/v1/predicates.yaml; outcome_eval.py):
    no record -> unknown; FAILED -> False; COMMITTED/PARTIAL/REVERSED with actual != requested -> False;
    COMMITTED with actual == requested -> True; any other status -> unknown."""
    recs = _records(ctx, "WmsTransferRecordObserved")
    if not recs:
        return None
    rec = recs[-1]
    status, actual, requested = rec.get("transferStatus"), rec.get("actualQuantity"), rec.get("requestedQuantity")
    want = ctx.inputs["quantity"]
    if status == "FAILED":
        return False
    if status in ("COMMITTED", "PARTIAL", "REVERSED") and (actual != want or requested != want):
        return False
    if status == "COMMITTED" and actual == want and requested == want:
        return True
    return None


def outcome_expedite(ctx):
    recs = _records(ctx, "PurchaseOrderObserved")
    if not recs:
        return None
    po = ctx.view.get("PurchaseOrder", ctx.inputs["po_id"])
    new, old = recs[-1].get("expectedAt"), po["props"].get("expectedAt") if po else None
    return None if new is None or old is None else new < old


def outcome_reschedule(ctx):
    recs = _records(ctx, "WorkOrderObserved")
    if not recs:
        return None
    new = recs[-1].get("plannedStart")
    return None if new is None else new == ctx.inputs["new_planned_start"]


def payload_transfer(ctx) -> dict:
    i = ctx.inputs
    return {"source": i["source_warehouse"], "destination": i["destination_warehouse"], "part": i["part"],
            "quantity": i["quantity"]}


def payload_expedite(ctx) -> dict:
    return {"expedite_fee": ctx.inputs["expedite_fee"], "$key": ctx.inputs["po_id"]}


def payload_reschedule(ctx) -> dict:
    return {"new_planned_start": ctx.inputs["new_planned_start"], "$key": ctx.inputs["work_order_id"]}


PRECONDITIONS = {
    "quantity >= 1": pre_quantity,
    "source != destination": pre_distinct,
    "source_available >= quantity": pre_source_available,
    "expedite_fee >= 0": pre_fee,
    "po_status not in [RECEIVED, CANCELLED]": pre_po_open,
    "work_order_status not in [DONE, CANCELLED]": pre_wo_open,
}
_T = "WMS_CDC observation within PT30S: the WmsTransferRecord correlated by action_execution_id has status COMMITTED and actual_quantity == requested_quantity (source.available decreases by quantity; destination.available increases by quantity)"
OUTCOMES = {
    _T: outcome_transfer,
    "ERP_CDC observation within PT30S: purchase_order.expected_at decreases": outcome_expedite,
    "MES_CDC observation within PT30S: work_order.planned_start changes to new_planned_start": outcome_reschedule,
}
PAYLOADS = {"transfer_inventory#0": payload_transfer, "expedite_purchase_order#0": payload_expedite,
            "reschedule_work_order#0": payload_reschedule}
