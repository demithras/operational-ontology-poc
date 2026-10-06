#!/usr/bin/env python3
"""Writes domains/manufacturing/seed.json: a small synthetic manufacturing dataset (canonical-incident shaped).

    .venv/bin/python scripts/build_mfg_seed.py

Synthetic data, not production data. Source of the shape: seed/fixtures/canonical_incident.yaml of the v1 POC
(WO-42 HIGH priority at risk for PX-17 at WH-A after PO-991 slips), extended with a second part (PX-900) with plenty
of stock so that large, unprotected transfers (over the approval threshold) can be exercised.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "domains" / "manufacturing" / "seed.json"
WHS = ["WH-A", "WH-B", "WH-C"]
ops: list[dict] = []


def link(lt, st, sk, dt, dk):
    ops.append({"op": "link", "type": lt, "src": [st, sk], "dst": [dt, dk], "props": {}})


PK = {"Warehouse": "warehouseId", "Part": "partId", "InventoryLot": "lotId", "WorkOrder": "workOrderId",
      "BomRequirement": "iri", "PurchaseOrder": "poId", "PurchaseOrderLine": "iri", "Supplier": "supplierId",
      "ProductionLine": "lineId", "EvidenceSnapshot": "iri", "IdentityMapping": "iri", "HumanActor": "actorId",
      "Decision": "decisionId"}


def mk(t, key, **props):
    ops.append({"op": "create", "type": t, "key": key, "props": {PK[t]: key, **props}})


for w in WHS:
    mk("Warehouse", w, region="region-1", capacityClass="standard")
mk("Part", "PX-17", description="reference part for the canonical incident", unit="each", criticality="HIGH")
mk("Part", "PX-900", description="bulk part", unit="each", criticality="LOW")
mk("Supplier", "S-7", status="ACTIVE", leadTimeDays=5, riskClass="MEDIUM")
mk("ProductionLine", "L-1", status="RUNNING", capabilities="assembly")
for lot, part, wh, oh, rs, q in [("LOT-A-PX17", "PX-17", "WH-A", 20, 0, "OK"), ("LOT-B-PX17", "PX-17", "WH-B", 140, 0, "OK"),
                                 ("LOT-C-PX900", "PX-900", "WH-C", 500, 0, "OK"), ("LOT-B-PX900", "PX-900", "WH-B", 10, 0, "OK"),
                                 ("LOT-A-PX900", "PX-900", "WH-A", 30, 0, "QUARANTINE")]:
    mk("InventoryLot", lot, onHand=oh, reserved=rs, qualityStatus=q)
    link("PartReferencing_part", "InventoryLot", lot, "Part", part)
    link("InventoryLot_warehouse", "InventoryLot", lot, "Warehouse", wh)
mk("WorkOrder", "WO-42", status="PLANNED", priority="HIGH", plannedStart=18, plannedFinish=40)
mk("WorkOrder", "WO-43", status="RUNNING", priority="LOW", plannedStart=30, plannedFinish=60)
for wo, wh, bom, part, qty in [("WO-42", "WH-A", "BOM-42-PX17", "PX-17", 80), ("WO-43", "WH-B", "BOM-43-PX900", "PX-900", 5)]:
    link("WorkOrder_warehouse", "WorkOrder", wo, "Warehouse", wh)
    link("WorkOrder_productionLine", "WorkOrder", wo, "ProductionLine", "L-1")
    mk("BomRequirement", bom, quantity=qty)
    link("BomRequirement_workOrder", "BomRequirement", bom, "WorkOrder", wo)
    link("BomRequirement_requiresPart", "BomRequirement", bom, "Part", part)
for po, st, exp, line, part, wh, qty in [("PO-991", "DELAYED", 120, "POL-991-1", "PX-17", "WH-A", 100),
                                         ("PO-992", "OPEN", 40, "POL-992-1", "PX-900", "WH-B", 50)]:
    mk("PurchaseOrder", po, status=st, promisedAt=8, expectedAt=exp)
    link("PurchaseOrder_suppliedBy", "PurchaseOrder", po, "Supplier", "S-7")
    mk("PurchaseOrderLine", line, quantity=qty)
    link("PurchaseOrderLine_purchaseOrder", "PurchaseOrderLine", line, "PurchaseOrder", po)
    link("PartReferencing_part", "PurchaseOrderLine", line, "Part", part)
    link("PurchaseOrderLine_destinationWarehouse", "PurchaseOrderLine", line, "Warehouse", wh)
mk("EvidenceSnapshot", "ES-1", snapshotObservedAt="2026-01-01T00:00:00+00:00", snapshotContentHash="0" * 64)
for iri, sid, part in [("IM-ERP", "PART-00192", "PX-17"), ("IM-MES", "COMP-A17", "PX-17"), ("IM-WMS", "SKU-88429", "PX-17")]:
    mk("IdentityMapping", iri, sourceLocalId=sid, mappingRuleId="canonical-incident", mappingRuleVersion="1")
    link("IdentityMapping_canonicalId", "IdentityMapping", iri, "Part", part)
mk("HumanActor", "planner-1", actorRole="planner")
mk("Decision", "D-1", decisionType="transfer", ontologyVersion="v3", shapeSetVersion="v3", authorizationModelVersion="v2",
   policyBundleVersion="v2", actionType="transfer_inventory", actionVersion=3, createdAt="2026-01-01T00:00:00+00:00",
   status="REQUIRES_APPROVAL", parametersJson=json.dumps({"quantity": 100, "part": "PX-900"}, sort_keys=True))
link("Decision_actor", "Decision", "D-1", "HumanActor", "planner-1")
link("Decision_evidenceSnapshot", "Decision", "D-1", "EvidenceSnapshot", "ES-1")


def rels(rel):  # region-level grants (planner/supervisor/senior_approver inherited by warehouse) expanded per warehouse
    return [["Warehouse", w, rel] for w in WHS]


human = lambda pid, role, rel: {"pid": pid, "roles": [role], "relations": rels(rel), "delegated_by": None}  # noqa: E731
planner = human("planner-1", "planner", "planner")
principals = [planner, human("junior-1", "junior_planner", "junior_planner"),
              human("supervisor-1", "supervisor", "supervisor"), human("senior-1", "senior_approver", "senior_approver"),
              {"pid": "agent-1", "roles": ["agent"], "relations": rels("agent_grant"), "delegated_by": planner},
              {"pid": "agent-orphan", "roles": ["agent"], "relations": rels("agent_grant"),
               "delegated_by": human("nobody-1", "none", "planner") | {"relations": []}}]
OUT.write_text(json.dumps({"description": "synthetic manufacturing seed (canonical-incident shaped)",
                           "principals": principals, "ops": ops}, indent=1, sort_keys=True) + "\n")
print("wrote", OUT, len(ops), "ops")
