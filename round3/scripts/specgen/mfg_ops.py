"""Neutral operational requirements for the manufacturing domain (hand-authored semantics, IR-checked coverage)."""
from .dsl import *  # noqa: F401,F403

SAFETY = {"default": 15, "overrides": [{"part": "PX-17", "warehouse": "WH-B", "units": 60},
                                      {"part": "PX-800501", "warehouse": "WH-B", "units": 60}]}
CONFIG = {"time_unit": "1 tick = 1 second of logical time", "evidence_max_age_ticks": 5,
          "approval_threshold_units": 80, "approval_threshold_cost": 500, "safety_stock_units": SAFETY}

_src = unique("InventoryLot", PartReferencing_part=inp("part"), InventoryLot_warehouse=inp("source_warehouse"))
_dst = unique("InventoryLot", PartReferencing_part=inp("part"), InventoryLot_warehouse=inp("destination_warehouse"))
_avail = lambda lot: sub(field(lot, "onHand"), field(lot, "reserved"))  # noqa: E731
_safety = {"read": "safety_stock", "args": {"part": inp("part"), "warehouse": inp("source_warehouse")}}
_fresh = lt(sub(now(), newest("EvidenceSnapshot", "snapshotObservedAt")), lit(CONFIG["evidence_max_age_ticks"] + 1))

TRANSFER_RULES = [
    {"id": "transfer-no-evidence", "decision": "deny", "description":
     "Deny when the source inventory lot for (part, source) is absent or ambiguous, or quantity is not an integer.",
     "when": or_(not_(exists(_src)), not_(is_int(inp("quantity"))))},
    {"id": "transfer-stale-evidence", "decision": "deny", "description":
     "Deny unless the newest EvidenceSnapshot exists and is at most evidence_max_age_ticks old.",
     "when": not_(_fresh)},
    {"id": "transfer-quarantine", "decision": "deny", "description":
     "Deny when the source lot or the destination lot (if one exists) has qualityStatus QUARANTINE.",
     "when": or_(eq(field(_src, "qualityStatus"), lit("QUARANTINE")),
                 and_(exists(_dst), eq(field(_dst, "qualityStatus"), lit("QUARANTINE"))))},
    {"id": "transfer-reservation-broken", "decision": "deny", "description":
     "Deny when the source lot has onHand < reserved.", "when": lt(field(_src, "onHand"), field(_src, "reserved"))},
    {"id": "transfer-safety-stock", "decision": "deny", "description":
     "Deny when onHand - reserved - quantity at the source would fall below the safety stock for (part, source).",
     "when": lt(sub(_avail(_src), inp("quantity")), _safety)},
    {"id": "transfer-protected-route", "decision": "deny", "description":
     "Deny when the route (part, source, destination) protects a HIGH-priority at-risk work order "
     "(read protecting_work_orders is non-empty) and the acting principal holds neither the planner nor the "
     "supervisor relation on the source warehouse.",
     "when": and_(ne(read("protecting_work_orders", part=inp("part"), source=inp("source_warehouse"),
                          destination=inp("destination_warehouse")), lit([])),
                  not_(or_(actor_holds("planner", inp("source_warehouse")),
                           actor_holds("supervisor", inp("source_warehouse")))))},
    {"id": "transfer-large-needs-approval", "decision": "require_approval", "description":
     "Quantity above approval_threshold_units needs approval (applies only when no deny rule matched).",
     "when": gt(inp("quantity"), lit(CONFIG["approval_threshold_units"]))},
]
TERMINAL_PO, TERMINAL_WO = ["RECEIVED", "CANCELLED"], ["DONE", "CANCELLED"]


def _op(name, summary, inputs, pre, rules, effects, gated, approval, outcome):
    return {"name": name, "summary": summary, "inputs": inputs, "preconditions": pre, "business_rules": rules,
            "effects": effects, "gated_inputs": gated, "immutable_after_authorization": gated,
            "idempotency": "required", "approval": approval, "expected_outcome": outcome}


def operations(ir_actions):
    by = {a["id"]: [ir_input(x) for x in a["inputs"]] for a in ir_actions}
    po = lambda: field(inp("po_id"), "status")  # noqa: E731
    wo = lambda: field(inp("work_order_id"), "status")  # noqa: E731
    return [
        _op("transfer_inventory", "Move stock of a part between two warehouses via the external WMS.", by["transfer_inventory"],
            [rule("quantity-positive-int", "quantity is an integer (booleans excluded) and >= 1",
                  and_(is_int(inp("quantity")), ge(inp("quantity"), lit(1)))),
             rule("endpoints-differ", "source_warehouse != destination_warehouse",
                  ne(inp("source_warehouse"), inp("destination_warehouse"))),
             rule("source-has-stock", "the source lot exists and onHand - reserved >= quantity",
                  and_(exists(_src), ge(_avail(_src), inp("quantity"))))],
            TRANSFER_RULES,
            [{"kind": "external", "adapter": "WMS", "target": "transfer",
              "payload": {"source": inp("source_warehouse"), "destination": inp("destination_warehouse"),
                          "part": inp("part"), "quantity": inp("quantity")},
              "note": "Exactly one WMS command per authorized request; WMS-side stock changes are the WMS's own."}],
            ["source_warehouse", "destination_warehouse", "part", "quantity", "work_order"],
            {"required_when_rule": "transfer-large-needs-approval", "approver_operation": "approval:large_transfer",
             "rules": ["approver is a principal different from the requester and outside the requester's delegation chain",
                       "approval binds to the exact inputs that were pending; any change needs a fresh decision"]},
            "WMS commits a transfer record with actual quantity == requested quantity; source available decreases and "
            "destination available increases by quantity."),
        _op("expedite_purchase_order", "Pay a fee to pull a purchase order's expected arrival earlier via the ERP.",
            by["expedite_purchase_order"],
            [rule("fee-nonneg-int", "expedite_fee is an integer >= 0", and_(is_int(inp("expedite_fee")), ge(inp("expedite_fee"), lit(0)))),
             rule("po-open", "the purchase order status is not RECEIVED or CANCELLED",
                  not_(in_(po(), TERMINAL_PO)))],
            [{"id": "expedite-closed-po", "decision": "deny", "description": "Deny when the PO is absent, has no status, "
              "has a terminal status, or the fee is not an integer.",
              "when": or_(not_(exists(inp("po_id"))), in_(po(), TERMINAL_PO), not_(is_int(inp("expedite_fee"))))},
             {"id": "expedite-large-fee-needs-approval", "decision": "require_approval",
              "description": "Fee above approval_threshold_cost needs approval.",
              "when": gt(inp("expedite_fee"), lit(CONFIG["approval_threshold_cost"]))}],
            [{"kind": "external", "adapter": "ERP", "target": "expedite",
              "payload": {"po_id": inp("po_id"), "expedite_fee": inp("expedite_fee")}}],
            ["po_id", "expedite_fee"],
            {"required_when_rule": "expedite-large-fee-needs-approval", "approver_operation": "approval:expedite",
             "rules": ["approver differs from the requester and is outside the requester's delegation chain"]},
            "ERP reports a smaller expectedAt for the purchase order."),
        _op("reschedule_work_order", "Change a work order's planned start via the MES.", by["reschedule_work_order"],
            [rule("wo-open", "the work order status is not DONE or CANCELLED", not_(in_(wo(), TERMINAL_WO)))],
            [{"id": "reschedule-closed-wo", "decision": "deny", "description":
              "Deny when the work order is absent, lacks status or priority, or is DONE/CANCELLED.",
              "when": or_(not_(exists(inp("work_order_id"))), in_(wo(), TERMINAL_WO))},
             {"id": "reschedule-high-priority-needs-approval", "decision": "require_approval",
              "description": "A HIGH-priority work order needs approval.",
              "when": eq(field(inp("work_order_id"), "priority"), lit("HIGH"))}],
            [{"kind": "external", "adapter": "MES", "target": "reschedule",
              "payload": {"work_order_id": inp("work_order_id"), "new_planned_start": inp("new_planned_start")}}],
            ["work_order_id", "new_planned_start"],
            {"required_when_rule": "reschedule-high-priority-needs-approval", "approver_operation": "approval:reschedule",
             "rules": ["approver differs from the requester and is outside the requester's delegation chain"]},
            "MES reports the work order plannedStart == new_planned_start."),
    ]
