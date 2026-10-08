"""Read-only fact extraction from the Engine's view (the Python port of reference_model/state.py derivations).

Everything here takes a read view and returns plain values. Nothing writes, nothing decides authority.
"""
from __future__ import annotations

from typing import Any

from . import data


def _one(view, link: str, t: str, key: Any):
    hits = view.follow(link, t, key)
    return hits[0]["key"] if hits else None


def lots(view) -> list[dict]:
    out = []
    for r in view.list("InventoryLot"):
        p = r["props"]
        out.append({"lot": r["key"], "part": _one(view, "PartReferencing_part", "InventoryLot", r["key"]),
                    "warehouse": _one(view, "InventoryLot_warehouse", "InventoryLot", r["key"]),
                    "on_hand": p.get("onHand", 0), "reserved": p.get("reserved", 0),
                    "quality": p.get("qualityStatus")})
    return out


def lot_for(view, part: Any, warehouse: Any) -> dict | None:
    hits = [x for x in lots(view) if x["part"] == part and x["warehouse"] == warehouse]
    return hits[0] if len(hits) == 1 else None  # ambiguous or absent -> no evidence


def available(lot: dict) -> int:
    return lot["on_hand"] - lot["reserved"]


def incoming_before(view, part: Any, warehouse: Any, deadline: int) -> int:
    """reference_model.derive._incoming_before: pending PO quantity for part into warehouse due by deadline."""
    total = 0
    for line in view.list("PurchaseOrderLine"):
        if _one(view, "PartReferencing_part", "PurchaseOrderLine", line["key"]) != part:
            continue
        if _one(view, "PurchaseOrderLine_destinationWarehouse", "PurchaseOrderLine", line["key"]) != warehouse:
            continue
        po = view.get("PurchaseOrder", _one(view, "PurchaseOrderLine_purchaseOrder", "PurchaseOrderLine", line["key"]))
        if po is None or po["props"].get("status") in data.TERMINAL_PO:
            continue
        if po["props"].get("expectedAt", 0) <= deadline:
            total += line["props"].get("quantity", 0)
    return total


def work_order(view, wo_id: Any) -> dict | None:
    r = view.get("WorkOrder", wo_id)
    if r is None:
        return None
    reqs: dict = {}
    for b in view.follow("BomRequirement_workOrder", "WorkOrder", wo_id, "in"):
        part = _one(view, "BomRequirement_requiresPart", "BomRequirement", b["key"])
        if part is None:   # the requiring link is hidden/absent: the requirement names no part (oracle loops over requiresPart links)
            continue
        reqs[part] = reqs.get(part, 0) + b["props"].get("quantity", 0)
    p = r["props"]
    return {"id": wo_id, "status": p.get("status"), "priority": p.get("priority"),
            "planned_start": p.get("plannedStart", 0), "warehouse": _one(view, "WorkOrder_warehouse", "WorkOrder", wo_id),
            "requirements": reqs}


def risk(view, wo_id: Any) -> dict:
    """reference_model.derive.work_order_risk (terminal or unknown work orders: zero shortage, not at risk)."""
    wo = work_order(view, wo_id)
    if wo is None or wo["status"] in data.TERMINAL_WO:
        return {"work_order_id": wo_id, "shortage": 0, "at_risk": False, "part_shortfalls": []}
    shortage, parts = 0, []
    for part, need in sorted(wo["requirements"].items(), key=lambda kv: str(kv[0])):
        lot = lot_for(view, part, wo["warehouse"])
        have = available(lot) if lot else 0
        short = max(0, need - have - incoming_before(view, part, wo["warehouse"], wo["planned_start"]))
        shortage += short
        if short > 0:
            parts.append([part, short])
    return {"work_order_id": wo_id, "shortage": shortage, "at_risk": shortage > 0, "part_shortfalls": parts}


def candidates(view, wo_id: Any) -> list[dict]:
    """projection_builder.compute.compute_transfer_candidates for one work order."""
    r, wo = risk(view, wo_id), work_order(view, wo_id)
    if wo is None or not r["at_risk"]:
        return []
    out = []
    for part, shortfall in r["part_shortfalls"]:
        for lot in lots(view):
            av = available(lot)
            if lot["part"] != part or lot["warehouse"] == wo["warehouse"] or av <= 0:
                continue
            out.append({"candidate_id": f"{wo_id}|{part}|{lot['warehouse']}", "work_order_id": wo_id, "part": part,
                        "destination_warehouse": wo["warehouse"], "source_warehouse": lot["warehouse"],
                        "candidate_quantity": min(av, shortfall)})
    return out


def protecting_work_orders(view, part: Any, src: Any, dst: Any) -> list:
    """Work orders for which (part, src, dst) is a transfer candidate and which are HIGH priority and at risk
    (services.decision_service.evidence._resolve_route_protection, PROTECTED case)."""
    out = []
    for r in view.list("WorkOrder"):
        wo = work_order(view, r["key"])
        if wo["priority"] != "HIGH" or wo["status"] in data.TERMINAL_WO:
            continue
        for c in candidates(view, r["key"]):
            if (c["part"], c["source_warehouse"], c["destination_warehouse"]) == (part, src, dst):
                out.append(r["key"])
                break
    return out


def _tick(x: Any) -> int | None:
    """Neutral time is an integer logical tick (P2a patch D1; Round 2 used ISO strings)."""
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def evidence_age_s(view, now: Any) -> float | None:
    """Ticks (= seconds) between ``now`` and the newest EvidenceSnapshot; None when there is none (fail closed -> STALE)."""
    times = [_tick(r["props"].get("snapshotObservedAt")) for r in view.list("EvidenceSnapshot")]
    times = [t for t in times if t is not None]
    n = _tick(now)
    if not times or n is None:
        return None
    return n - max(times)


def freshness(view, now: Any) -> str:
    age = evidence_age_s(view, now)
    return "FRESH" if age is not None and age <= data.MAX_EVIDENCE_FRESHNESS_S else "STALE"


def holds(principal, obj_type: str, key: Any, relation: str) -> bool:
    # P2a patch D5: a delegated request acts with its delegation chain (agent on behalf of P): any link may hold the relation
    return any((obj_type, key, relation) in p.relations for p in principal.chain())
