"""Constraint expression bindings (pred(ctx) -> bool, True = holds on the would-be state ctx.view)."""
from __future__ import annotations

from . import data, facts, functions


def _all_lots(ctx, pred) -> bool:
    return all(pred(x) for x in facts.lots(ctx.view))


def _enum(type_name: str, prop: str, allowed):
    return lambda ctx: all(r["props"].get(prop) is None or r["props"][prop] in allowed for r in ctx.view.list(type_name))


def _planned(ctx, target: str):
    hits = [p["payload"] for p in ctx.planned if p["target"] == target]
    return hits[0] if len(hits) == 1 else None


def _transfer_ends(ctx):
    p = _planned(ctx, "WMS")
    if p is None:
        return None
    src, dst = facts.lot_for(ctx.view, p["part"], p["source"]), facts.lot_for(ctx.view, p["part"], p["destination"])
    return p, src, dst


def safety_stock_holds(ctx) -> bool:
    got = _transfer_ends(ctx)
    if got is None or got[1] is None:
        return False
    p, src, _ = got
    return facts.available(src) - p["quantity"] >= data.safety_stock(p["part"], p["source"])


def quarantine_free(ctx) -> bool:
    got = _transfer_ends(ctx)
    if got is None or got[1] is None:
        return False
    return "QUARANTINE" not in (got[1]["quality"], got[2]["quality"] if got[2] else "OK")


def evidence_fresh(ctx) -> bool:
    return facts.freshness(ctx.view, ctx.now) == "FRESH"


def transfer_below_threshold(ctx) -> bool:  # soft: a flag when the transfer needed approval
    p = _planned(ctx, "WMS")
    return p is not None and p["quantity"] <= data.APPROVAL_THRESHOLD_UNITS


def expedite_below_threshold(ctx) -> bool:  # soft
    p = _planned(ctx, "ERP")
    return p is not None and p["expedite_fee"] <= data.APPROVAL_THRESHOLD_COST


def reschedule_not_high(ctx) -> bool:  # soft
    p = _planned(ctx, "MES")
    wo = ctx.view.get("WorkOrder", p["$key"]) if p is not None else None
    return wo is not None and wo["props"].get("priority") != "HIGH"


def quantity_positive(ctx) -> bool:
    return all(r["props"].get("quantity") is None or r["props"]["quantity"] >= 1 for r in ctx.view.list("ActionExecution"))


def endpoints_disjoint(ctx) -> bool:
    for r in ctx.view.list("ActionExecution"):
        a = ctx.view.follow("ActionExecution_sourceWarehouse", "ActionExecution", r["key"])
        b = ctx.view.follow("ActionExecution_destinationWarehouse", "ActionExecution", r["key"])
        if a and b and a[0]["key"] == b[0]["key"]:
            return False
    return True


def applied_at_most_once(ctx) -> bool:
    # The store keys ActionExecution/WmsTransferRecord by actionExecutionId, so a duplicate cannot exist in a state
    # that was accepted; this re-checks it on the would-be state (weak by construction, disclosed).
    ks = [r["key"] for r in ctx.view.list("ActionExecution")] + [r["key"] for r in ctx.view.list("WmsTransferRecord")]
    return len(ks) == len(set(ks))


def decision_hash_matches(ctx) -> bool:
    for r in ctx.view.list("Decision"):
        stored = r["props"].get("decisionContentHash")
        if stored is not None and stored != functions.decision_content_hash(ctx.view, {"decision": r["key"]}):
            return False
    return True


def no_effect_without_approval(ctx) -> bool:
    for r in ctx.view.list("Decision"):
        if r["props"].get("status") in data.NO_EFFECT_STATUSES:
            if ctx.view.follow("Decision_actionExecution", "Decision", r["key"]):
                return False
    return True


IMPLEMENTATIONS = {
    "shacl:fac:InventoryLotShape#onHand minInclusive 0": lambda c: _all_lots(c, lambda x: x["on_hand"] >= 0),
    "shacl:fac:InventoryLotShape#reserved minInclusive 0": lambda c: _all_lots(c, lambda x: x["reserved"] >= 0),
    "invariant: onHand >= reserved": lambda c: _all_lots(c, lambda x: x["on_hand"] >= x["reserved"]),
    "invariant: onHand - reserved >= 0": lambda c: _all_lots(c, lambda x: x["on_hand"] - x["reserved"] >= 0),
    "enum:OK|QUARANTINE on qualityStatus": _enum("InventoryLot", "qualityStatus", data.QUALITY_VOCAB),
    "enum:PLANNED|RELEASED|RUNNING|DONE|CANCELLED on status": _enum("WorkOrder", "status", data.WORK_ORDER_STATUS_VOCAB),
    "shacl:oo:DecisionShape#status sh:in": _enum("Decision", "status", data.DECISION_STATUS_VOCAB),
    "shacl:oo:OutcomeShape#reconciliationState sh:in": _enum("Outcome", "reconciliationState", data.RECONCILIATION_VOCAB),
    "shacl:oo:ActionExecutionShape#quantity minInclusive 1": quantity_positive,
    "shacl:oo:ActionExecutionShape#sourceWarehouse disjoint destinationWarehouse": endpoints_disjoint,
    "invariant: actionExecutionId applied at most once": applied_at_most_once,
    "invariant: recomputed decision_content_hash equals the stored hash": decision_hash_matches,
    "invariant: denial/pending statuses carry no execution or outcome": no_effect_without_approval,
    "rego:factory.inventory.transfer_v2#remaining >= safety_stock": safety_stock_holds,
    "rego:factory.inventory.transfer_v2#no QUARANTINE on source or destination": quarantine_free,
    "closure.max_evidence_freshness_s <= 5": evidence_fresh,
    "quantity <= approval_threshold_units (80) without approval": transfer_below_threshold,
    "expedite_fee <= approval_threshold_cost (500) without approval": expedite_below_threshold,
    "priority != HIGH without approval": reschedule_not_high,
}
