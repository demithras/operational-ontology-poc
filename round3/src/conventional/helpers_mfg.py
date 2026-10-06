"""Manufacturing helper reads, implemented from the prose in spec/ops/manufacturing.json (`helpers`)."""
from __future__ import annotations

from .interp import Ctx, ref_key
from .worldview import key_of


def _lot(ctx: Ctx, part: str, wh: str) -> str | None:
    v = ctx.view
    by_part = {key_of(s) for s in v.sources("PartReferencing_part", "Part", part)
               if s.startswith("InventoryLot:")}
    by_wh = {key_of(s) for s in v.sources("InventoryLot_warehouse", "Warehouse", wh)}
    hit = by_part & by_wh
    return next(iter(hit)) if len(hit) == 1 else None


def safety_stock(ctx: Ctx, part, warehouse) -> int:
    cfg = ctx.config["safety_stock_units"]
    for o in cfg["overrides"]:
        if o["part"] == ref_key(part) and o["warehouse"] == ref_key(warehouse):
            return o["units"]
    return cfg["default"]


def available_quantity(ctx: Ctx, lot) -> int:
    p = ctx.view.props("InventoryLot", ref_key(lot)) or {}
    return int(p.get("onHand") or 0) - int(p.get("reserved") or 0)


def incoming_before(ctx: Ctx, part, warehouse, deadline) -> int:
    v, part, wh, total = ctx.view, ref_key(part), ref_key(warehouse), 0
    for line, p in v.items("PurchaseOrderLine"):
        if not (v.has_link("PartReferencing_part", f"PurchaseOrderLine:{line}", f"Part:{part}")
                and v.has_link("PurchaseOrderLine_destinationWarehouse", f"PurchaseOrderLine:{line}", f"Warehouse:{wh}")):
            continue
        pos = v.targets("PurchaseOrderLine_purchaseOrder", "PurchaseOrderLine", line)
        po = v.props("PurchaseOrder", key_of(pos[0])) if pos else None
        if po is None or po.get("status") in ("RECEIVED", "CANCELLED"):
            continue
        if int(po.get("expectedAt") or 0) <= (deadline if type(deadline) is int else 0):
            total += int(p.get("quantity") or 0)
    return total


def _wo_warehouse(ctx: Ctx, wo: str) -> str | None:
    t = ctx.view.targets("WorkOrder_warehouse", "WorkOrder", wo)
    return key_of(t[0]) if t else None


def _shorts(ctx: Ctx, wo: str) -> dict[str, int]:
    p = ctx.view.props("WorkOrder", wo)
    if p is None or p.get("status") in ("DONE", "CANCELLED"):
        return {}
    need: dict[str, int] = {}
    for bom, bp in ctx.view.items("BomRequirement"):
        if ctx.view.has_link("BomRequirement_workOrder", f"BomRequirement:{bom}", f"WorkOrder:{wo}"):
            for t in ctx.view.targets("BomRequirement_requiresPart", "BomRequirement", bom):
                need[key_of(t)] = need.get(key_of(t), 0) + int(bp.get("quantity") or 0)
    wh, out = _wo_warehouse(ctx, wo), {}
    for part in sorted(need):
        lot = _lot(ctx, part, wh) if wh else None
        have = available_quantity(ctx, lot) if lot else 0
        inc = incoming_before(ctx, part, wh, p.get("plannedStart")) if wh else 0
        out[part] = max(0, need[part] - have - inc)
    return out


def work_order_risk(ctx: Ctx, work_order) -> dict:
    wo = ref_key(work_order)
    shortage = sum(_shorts(ctx, wo).values())
    return {"work_order_id": wo, "shortage": shortage, "at_risk": shortage > 0}


def transfer_candidates(ctx: Ctx, work_order) -> list[dict]:
    wo = ref_key(work_order)
    shorts, dest, out = _shorts(ctx, wo), _wo_warehouse(ctx, wo), []
    for part in sorted(p for p, s in shorts.items() if s > 0):
        for lot in ctx.view.keys("InventoryLot"):
            if not ctx.view.has_link("PartReferencing_part", f"InventoryLot:{lot}", f"Part:{part}"):
                continue
            w = ctx.view.targets("InventoryLot_warehouse", "InventoryLot", lot)
            src, avail = (key_of(w[0]) if w else None), available_quantity(ctx, lot)
            if src is not None and src != dest and avail > 0:
                out.append({"candidate_id": f"{wo}|{part}|{src}", "work_order_id": wo, "part": part,
                            "destination_warehouse": dest, "source_warehouse": src,
                            "candidate_quantity": min(avail, shorts[part])})
    return out


def protecting_work_orders(ctx: Ctx, part, source, destination) -> list[str]:
    want = (ref_key(part), ref_key(source), ref_key(destination))
    out = []
    for wo, p in ctx.view.items("WorkOrder"):
        if p.get("priority") == "HIGH" and p.get("status") not in ("DONE", "CANCELLED"):
            if any((c["part"], c["source_warehouse"], c["destination_warehouse"]) == want
                   for c in transfer_candidates(ctx, wo)):
                out.append(wo)
    return out


def recommend_transfer_for_work_order(ctx: Ctx, work_order):
    risk, cands = work_order_risk(ctx, work_order), transfer_candidates(ctx, work_order)
    if not risk["at_risk"] or not cands:
        return None
    c = sorted(cands, key=lambda x: (-x["candidate_quantity"], x["candidate_id"]))[0]
    return {"action_type": "transfer_inventory", "context": {},
            "parameters": {"source_warehouse": c["source_warehouse"], "destination_warehouse": c["destination_warehouse"],
                           "part": c["part"], "quantity": min(c["candidate_quantity"], risk["shortage"]),
                           "work_order": c["work_order_id"]}}


def resolve_canonical_id(ctx: Ctx, source_local_id):
    for k, p in ctx.view.items("IdentityMapping"):
        if p.get("sourceLocalId") == source_local_id:
            t = ctx.view.targets("IdentityMapping_canonicalId", "IdentityMapping", k)
            if t:
                return key_of(t[0])
    return source_local_id


HELPERS = {f.__name__: f for f in (safety_stock, available_quantity, incoming_before, work_order_risk,
                                   transfer_candidates, protecting_work_orders,
                                   recommend_transfer_for_work_order, resolve_canonical_id)}
