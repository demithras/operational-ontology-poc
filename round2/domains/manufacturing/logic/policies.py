"""Policy expression bindings (pred(ctx) -> bool, True = the policy applies), ported from contracts/policies/*.rego.

Each rego package yields one shared ``decision`` function (deny > require_approval > allow, exactly as the rego
``decision`` rules); the three IR policies of an action are thin views of it. Read-only: only ctx.view / inputs.
"""
from __future__ import annotations

from . import data, facts


def _transfer_evidence(ctx) -> dict | None:
    """The policy input of contracts/policies/v2/transfer_inventory.rego, or None when invalid (valid_input false)."""
    i, v = ctx.inputs, ctx.view
    src, dst, part, q = i["source_warehouse"], i["destination_warehouse"], i["part"], i["quantity"]
    lot = facts.lot_for(v, part, src)
    if lot is None or not isinstance(q, int) or isinstance(q, bool):
        return None
    dlot = facts.lot_for(v, part, dst)
    return {"on_hand": lot["on_hand"], "reserved": lot["reserved"], "reservation_ok": lot["on_hand"] >= lot["reserved"],
            "safety_stock": data.safety_stock(part, src), "freshness": facts.freshness(v, ctx.now),
            "src_quality": lot["quality"], "dst_quality": "OK" if dlot is None else dlot["quality"], "quantity": q}


def may_mitigate_high_priority(principal, src) -> bool:
    """can_mitigate_high_priority = planner or supervisor on the source warehouse (contracts/authorization/v2/model.fga)."""
    return facts.holds(principal, "Warehouse", src, "planner") or facts.holds(principal, "Warehouse", src, "supervisor")


def _protection_denies(ctx) -> bool:
    """ADR-0003 protected route: a transfer that mitigates a fresh HIGH-priority at-risk work order additionally needs
    can_mitigate_high_priority. The Engine's authority gate never requests the IR capability
    action:mitigate_high_priority, so this reads the principal's relations here (disclosed deviation, see
    provenance-logic.md)."""
    i = ctx.inputs
    if not facts.protecting_work_orders(ctx.view, i["part"], i["source_warehouse"], i["destination_warehouse"]):
        return False
    return not may_mitigate_high_priority(ctx.principal, i["source_warehouse"])


def transfer_hard_deny(ctx) -> bool:
    ev = _transfer_evidence(ctx)
    if ev is None or ev["freshness"] != "FRESH":
        return True
    if "QUARANTINE" in (ev["src_quality"], ev["dst_quality"]) or not ev["reservation_ok"]:
        return True
    if ev["on_hand"] - ev["reserved"] - ev["quantity"] < ev["safety_stock"]:
        return True
    return _protection_denies(ctx)


def transfer_needs_approval(ctx) -> bool:
    ev = _transfer_evidence(ctx)
    return ev is not None and ev["quantity"] > data.APPROVAL_THRESHOLD_UNITS


def transfer_decision(ctx) -> str:
    if transfer_hard_deny(ctx):
        return "deny"
    return "require_approval" if transfer_needs_approval(ctx) else "allow"


def _expedite_ev(ctx):
    po = ctx.view.get("PurchaseOrder", ctx.inputs["po_id"])
    fee = ctx.inputs["expedite_fee"]
    if po is None or po["props"].get("status") is None or not isinstance(fee, int) or isinstance(fee, bool):
        return None
    return {"status": po["props"]["status"], "fee": fee}


def _expedite_hard_deny(ctx) -> bool:
    ev = _expedite_ev(ctx)
    return ev is None or ev["status"] in data.TERMINAL_PO


def _expedite_needs_approval(ctx) -> bool:
    ev = _expedite_ev(ctx)
    return ev is not None and ev["status"] not in data.TERMINAL_PO and ev["fee"] > data.APPROVAL_THRESHOLD_COST


def _reschedule_ev(ctx):
    wo = ctx.view.get("WorkOrder", ctx.inputs["work_order_id"])
    if wo is None or wo["props"].get("status") is None or wo["props"].get("priority") is None:
        return None
    return wo["props"]


def _reschedule_hard_deny(ctx) -> bool:
    ev = _reschedule_ev(ctx)
    return ev is None or ev["status"] in data.TERMINAL_WO


def _reschedule_needs_approval(ctx) -> bool:
    ev = _reschedule_ev(ctx)
    return ev is not None and ev["status"] not in data.TERMINAL_WO and ev["priority"] == "HIGH"


def _decided(hard, needs, valid):
    def decision(ctx):
        if hard(ctx):
            return "deny"
        return "require_approval" if needs(ctx) else ("allow" if valid(ctx) else "deny")
    return decision


_expedite_decision = _decided(_expedite_hard_deny, _expedite_needs_approval, lambda c: _expedite_ev(c) is not None)
_reschedule_decision = _decided(_reschedule_hard_deny, _reschedule_needs_approval, lambda c: _reschedule_ev(c) is not None)

IMPLEMENTATIONS = {
    "rego:factory.inventory.transfer_v2#hard_deny": transfer_hard_deny,
    "rego:factory.inventory.transfer_v2#needs_approval": transfer_needs_approval,
    "rego:factory.inventory.transfer_v2#allow": lambda c: transfer_decision(c) == "allow",
    "rego:factory.purchase_order.expedite#hard_deny": _expedite_hard_deny,
    "rego:factory.purchase_order.expedite#needs_approval": _expedite_needs_approval,
    "rego:factory.purchase_order.expedite#allow": lambda c: _expedite_decision(c) == "allow",
    "rego:factory.work_order.reschedule#hard_deny": _reschedule_hard_deny,
    "rego:factory.work_order.reschedule#needs_approval": _reschedule_needs_approval,
    "rego:factory.work_order.reschedule#allow": lambda c: _reschedule_decision(c) == "allow",
}
