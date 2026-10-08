"""Policy expression bindings (pred(ctx) -> bool, True = the policy applies), ported from contracts/policies/*.rego.

Each rego package yields one shared ``decision`` function (deny > require_approval > allow, exactly as the rego
``decision`` rules); the three IR policies of an action are thin views of it. Read-only: only ctx.view / inputs.
"""
from __future__ import annotations

from . import data, facts

# Business rules that gate a request (relations, thresholds, field tests) are DATA of the ops spec this deployment was
# booted with, evaluated by paladin.opsrules.RuleSet; nothing below names a relation or a threshold (G3-E29, fix6).
OP_TRANSFER, OP_EXPEDITE, OP_RESCHEDULE = "transfer_inventory", "expedite_purchase_order", "reschedule_work_order"
ROUTE_RULE = "transfer-protected-route"


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


def _expedite_ev(ctx):
    po = ctx.view.get("PurchaseOrder", ctx.inputs["po_id"])
    fee = ctx.inputs["expedite_fee"]
    if po is None or po["props"].get("status") is None or not isinstance(fee, int) or isinstance(fee, bool):
        return None
    return {"status": po["props"]["status"], "fee": fee}


def _reschedule_ev(ctx):
    wo = ctx.view.get("WorkOrder", ctx.inputs["work_order_id"])
    if wo is None or wo["props"].get("status") is None or wo["props"].get("priority") is None:
        return None
    return wo["props"]


def _expedite_hard_deny(ctx) -> bool:
    ev = _expedite_ev(ctx)
    return ev is None or ev["status"] in data.TERMINAL_PO


def _reschedule_hard_deny(ctx) -> bool:
    ev = _reschedule_ev(ctx)
    return ev is None or ev["status"] in data.TERMINAL_WO


def _decided(hard, gated, valid):
    def decision(ctx):
        if hard(ctx):
            return "deny"
        return "require_approval" if gated(ctx) else ("allow" if valid(ctx) else "deny")
    return decision


def make(rules) -> dict:
    """Policy bindings for the ops spec behind ``rules`` (paladin.opsrules.RuleSet); every rule that names a relation
    or a threshold is evaluated from that spec, so editing the spec edits the decision."""
    def gate(op: str) -> str:  # the rule the spec says makes this operation need an approval
        return rules.rule(op, rules.gating_rule(op))["id"]

    def route_denies(ctx) -> bool:
        return rules.matches(ctx, OP_TRANSFER, ROUTE_RULE)

    def transfer_hard_deny(ctx) -> bool:
        ev = _transfer_evidence(ctx)
        if ev is None or ev["freshness"] != "FRESH":
            return True
        if "QUARANTINE" in (ev["src_quality"], ev["dst_quality"]) or not ev["reservation_ok"]:
            return True
        if ev["on_hand"] - ev["reserved"] - ev["quantity"] < ev["safety_stock"]:
            return True
        return route_denies(ctx)

    def transfer_gated(ctx) -> bool:
        return _transfer_evidence(ctx) is not None and rules.matches(ctx, OP_TRANSFER, gate(OP_TRANSFER))

    def transfer_decision(ctx) -> str:
        if transfer_hard_deny(ctx):
            return "deny"
        return "require_approval" if transfer_gated(ctx) else "allow"

    def expedite_gated(ctx) -> bool:
        ev = _expedite_ev(ctx)
        return ev is not None and ev["status"] not in data.TERMINAL_PO and rules.matches(ctx, OP_EXPEDITE, gate(OP_EXPEDITE))

    def reschedule_gated(ctx) -> bool:
        ev = _reschedule_ev(ctx)
        return ev is not None and ev["status"] not in data.TERMINAL_WO and rules.matches(ctx, OP_RESCHEDULE, gate(OP_RESCHEDULE))

    expedite = _decided(_expedite_hard_deny, expedite_gated, lambda c: _expedite_ev(c) is not None)
    reschedule = _decided(_reschedule_hard_deny, reschedule_gated, lambda c: _reschedule_ev(c) is not None)
    return {
        "rego:factory.inventory.transfer_v2#hard_deny": transfer_hard_deny,
        "rego:factory.inventory.transfer_v2#needs_approval": transfer_gated,
        "rego:factory.inventory.transfer_v2#allow": lambda c: transfer_decision(c) == "allow",
        "rego:factory.purchase_order.expedite#hard_deny": _expedite_hard_deny,
        "rego:factory.purchase_order.expedite#needs_approval": expedite_gated,
        "rego:factory.purchase_order.expedite#allow": lambda c: expedite(c) == "allow",
        "rego:factory.work_order.reschedule#hard_deny": _reschedule_hard_deny,
        "rego:factory.work_order.reschedule#needs_approval": reschedule_gated,
        "rego:factory.work_order.reschedule#allow": lambda c: reschedule(c) == "allow",
    }
