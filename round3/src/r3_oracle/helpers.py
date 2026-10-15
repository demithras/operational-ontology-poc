"""Helper registry. Manufacturing helpers are implemented here from the PROSE of spec/ops/manufacturing.json
(helpers + reads); project helpers live in helpers_project.py. One function each; first argument is the View."""
from __future__ import annotations

from .helpers_project import PROJECT_HELPERS
from .view import Ref, View


def _int(x) -> int:
    return x if isinstance(x, int) and not isinstance(x, bool) else 0


def safety_stock(v: View, part, warehouse) -> int:
    """config.safety_stock_units override for (part, warehouse) if listed, else the default."""
    cfg = v.config["safety_stock_units"]
    pk = part[1] if isinstance(part, tuple) else part
    wk = warehouse[1] if isinstance(warehouse, tuple) else warehouse
    for o in cfg["overrides"]:
        if o["part"] == pk and o["warehouse"] == wk:
            return o["units"]
    return cfg["default"]


def _lot(v: View, part: Ref, wh: Ref):
    hits = [lot for lot in v.refs_of("InventoryLot")
            if v.has_link("PartReferencing_part", lot, part) and v.has_link("InventoryLot_warehouse", lot, wh)]
    return hits[0] if len(hits) == 1 else None


def available_quantity(v: View, lot: Ref) -> int:
    return _int(v.field(lot, "onHand")) - _int(v.field(lot, "reserved"))


def incoming_before(v: View, part: Ref, warehouse: Ref, deadline) -> int:
    total = 0
    for line in v.refs_of("PurchaseOrderLine"):
        if not (v.has_link("PartReferencing_part", line, part)
                and v.has_link("PurchaseOrderLine_destinationWarehouse", line, warehouse)):
            continue
        pos = v.out("PurchaseOrderLine_purchaseOrder", line)
        if not pos or not v.exists(pos[0]) or v.field(pos[0], "status") in ("RECEIVED", "CANCELLED"):
            continue
        exp = v.field(pos[0], "expectedAt")
        if _int(exp) <= _int(deadline):
            total += _int(v.field(line, "quantity"))
    return total


def work_order_risk(v: View, work_order: Ref) -> dict:
    wo = v.get(work_order)
    none = {"work_order_id": work_order[1], "shortage": 0, "at_risk": False, "shorts": []}
    if wo is None or wo.get("status") in ("DONE", "CANCELLED"):
        return none
    need: dict[str, int] = {}
    for b in v.refs_of("BomRequirement"):
        if v.has_link("BomRequirement_workOrder", b, work_order):
            for p in v.out("BomRequirement_requiresPart", b):
                need[p[1]] = need.get(p[1], 0) + _int(v.field(b, "quantity"))
    whs = v.out("WorkOrder_warehouse", work_order)
    wh = whs[0] if whs else None
    shorts = []
    for pk in sorted(need):
        lot = _lot(v, ("Part", pk), wh) if wh else None
        have = available_quantity(v, lot) if lot else 0
        inc = incoming_before(v, ("Part", pk), wh, wo.get("plannedStart")) if wh else 0
        shorts.append((pk, max(0, need[pk] - have - inc)))
    total = sum(s for _, s in shorts)
    return {"work_order_id": work_order[1], "shortage": total, "at_risk": total > 0, "shorts": shorts}


def transfer_candidates(v: View, work_order: Ref) -> list[dict]:
    r = work_order_risk(v, work_order)
    if not r["at_risk"]:
        return []
    wh = v.out("WorkOrder_warehouse", work_order)[0]
    out = []
    for pk, short in r["shorts"]:
        if short <= 0:
            continue
        for lot in v.refs_of("InventoryLot"):
            if not v.has_link("PartReferencing_part", lot, ("Part", pk)):
                continue
            lw = v.out("InventoryLot_warehouse", lot)
            if not lw or lw[0] == wh:
                continue
            avail = available_quantity(v, lot)
            if avail > 0:
                out.append({"candidate_id": f"{work_order[1]}|{pk}|{lw[0][1]}", "work_order_id": work_order[1],
                            "part": pk, "destination_warehouse": wh[1], "source_warehouse": lw[0][1],
                            "candidate_quantity": min(avail, short)})
    return out


def protecting_work_orders(v: View, part, source, destination) -> list[str]:
    key = lambda x: x[1] if isinstance(x, tuple) else x  # noqa: E731
    out = []
    for wo in v.refs_of("WorkOrder"):
        if v.field(wo, "priority") != "HIGH" or v.field(wo, "status") in ("DONE", "CANCELLED"):
            continue
        if any(c["part"] == key(part) and c["source_warehouse"] == key(source)
               and c["destination_warehouse"] == key(destination) for c in transfer_candidates(v, wo)):
            out.append(wo[1])
    return sorted(out)


MFG_HELPERS = {f.__name__: f for f in (safety_stock, available_quantity, incoming_before, work_order_risk,
                                       transfer_candidates, protecting_work_orders)}
REGISTRY = {**MFG_HELPERS, **PROJECT_HELPERS}
