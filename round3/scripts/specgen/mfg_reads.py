"""Manufacturing read operations (IR functions), helpers, unsupported items and invariants."""
from .dsl import *  # noqa: F401,F403

_lot = unique("InventoryLot", PartReferencing_part=inp("part"), InventoryLot_warehouse=inp("warehouse"))


def reads(ir_funcs):
    by = {f["id"]: [ir_input(x) for x in f["inputs"]] for f in ir_funcs}
    return [
        {"name": "available_quantity", "inputs": by["available_quantity"], "output": "integer",
         "description": "onHand - reserved of the lot (missing onHand/reserved count as 0).",
         "expr": sub(field(inp("lot"), "onHand"), field(inp("lot"), "reserved"))},
        {"name": "incoming_before", "inputs": by["incoming_before"], "output": "integer",
         "description": "Sum of PurchaseOrderLine.quantity over lines whose PartReferencing_part == part and "
         "PurchaseOrderLine_destinationWarehouse == warehouse, whose purchase order (PurchaseOrderLine_purchaseOrder) "
         "exists, is not RECEIVED/CANCELLED and has expectedAt <= deadline (missing expectedAt counts as 0)."},
        {"name": "work_order_risk", "inputs": by["work_order_risk"], "output": "json",
         "description": "{work_order_id, shortage, at_risk}. Unknown or DONE/CANCELLED work order: shortage 0, at_risk false. "
         "Otherwise requirements = sum BomRequirement.quantity per required part (BomRequirement_workOrder, "
         "BomRequirement_requiresPart). For each part in ascending string order: have = available_quantity of the unique lot "
         "(part, WorkOrder_warehouse) or 0 if none/ambiguous; short = max(0, need - have - incoming_before(part, work-order "
         "warehouse, plannedStart)); shortage = sum of shorts; at_risk = shortage > 0."},
        {"name": "recommend_transfer_for_work_order", "inputs": by["recommend_transfer_for_work_order"],
         "output": "json|null",
         "description": "null unless work_order_risk.at_risk and transfer_candidates is non-empty. Otherwise take the candidate "
         "with the largest candidate_quantity (ties: smallest candidate_id) and return {action_type: transfer_inventory, "
         "parameters: {source_warehouse, destination_warehouse, part, quantity: min(candidate_quantity, shortage), "
         "work_order}, context: {}}. A recommendation is advice, not an authorization."},
        {"name": "resolve_canonical_id", "inputs": by["resolve_canonical_id"], "output": "string|null",
         "description": "Find the IdentityMapping whose sourceLocalId == source_local_id (iterate in key order) and return the key "
         "of the resource linked by IdentityMapping_canonicalId; if no mapping resolves, return source_local_id unchanged."},
    ]


HELPERS = [
    {"name": "safety_stock", "inputs": [i("part", "string"), i("warehouse", "string")], "output": "integer",
     "description": "config.safety_stock_units override for (part, warehouse) if listed, else the default."},
    {"name": "transfer_candidates", "inputs": [i("work_order", "resource", True, "WorkOrder")], "output": "json",
     "description": "Empty unless work_order_risk(work_order).at_risk. For each part with positive short (ascending part) and "
     "each InventoryLot of that part whose warehouse != the work order's warehouse and available_quantity > 0: candidate "
     "{candidate_id: '<wo>|<part>|<lot warehouse>', work_order_id, part, destination_warehouse: work order's warehouse, "
     "source_warehouse: lot warehouse, candidate_quantity: min(available, short)}."},
    {"name": "protecting_work_orders", "inputs": [i("part", "string"), i("source", "string"), i("destination", "string")],
     "output": "list",
     "description": "Keys of WorkOrders with priority HIGH, status not DONE/CANCELLED, having a transfer_candidate whose "
     "(part, source_warehouse, destination_warehouse) equals the arguments. This protects the route of a high-priority at-risk "
     "work order from being drained by an unrelated transfer."},
]

UNSUPPORTED = [{"name": "decision_content_hash", "kind": "function",
                "reason": "Hashes a control-plane Decision record (ontology/shape/authorization-model/policy-bundle versions, "
                "actor, evidence snapshot). Those are Engine provenance concepts with no neutral operational meaning; "
                "provenance integrity is measured separately (H27) with its own corpus."}]

EXCLUDED_TYPES = {
    "Decision": "control-plane decision record", "DecisionActivity": "control-plane provenance", "ActionExecution": "control-plane execution record",
    "Outcome": "control-plane reconciliation record", "HumanActor": "identity is supplied by auth spec", "SoftwareAgent": "identity is supplied by auth spec",
    "AuthorizationCheck": "control-plane audit", "PolicyEvaluation": "control-plane audit", "ConformanceCheck": "control-plane audit",
    "Observation": "ingestion plumbing", "SourcePosition": "ingestion plumbing", "IdentityResolutionActivity": "ingestion plumbing",
    "QuarantinedIdentity": "ingestion plumbing", "WmsTransferRecord": "WMS-side record; lives in the external system, observed via external effects"}

INVARIANTS = [
    {"id": "inventory-on-hand-nonnegative", "text": "InventoryLot.onHand >= 0", "ir": "inventory-on-hand-nonnegative"},
    {"id": "inventory-reserved-nonnegative", "text": "InventoryLot.reserved >= 0", "ir": "inventory-reserved-nonnegative"},
    {"id": "inventory-on-hand-covers-reserved", "text": "onHand >= reserved", "ir": "inventory-on-hand-covers-reserved"},
    {"id": "inventory-available-nonnegative", "text": "onHand - reserved >= 0", "ir": "inventory-available-nonnegative"},
    {"id": "quality-vocabulary", "text": "qualityStatus in {OK, QUARANTINE}", "ir": "quality-status-vocabulary"},
    {"id": "work-order-status-vocabulary", "text": "WorkOrder.status in {PLANNED, RELEASED, RUNNING, DONE, CANCELLED}", "ir": "work-order-status-vocabulary"},
    {"id": "transfer-endpoints-disjoint", "text": "no transfer with source == destination", "ir": "transfer-endpoints-disjoint"},
    {"id": "transfer-safety-stock", "text": "no committed transfer leaves source available below safety stock", "ir": "transfer-safety-stock"},
    {"id": "transfer-quarantine-blocked", "text": "no committed transfer touches a QUARANTINE lot", "ir": "transfer-quarantine-blocked"},
    {"id": "evidence-freshness", "text": "no committed transfer on stale evidence", "ir": "evidence-freshness"},
    {"id": "transfer-approval-threshold", "text": "no committed transfer above the unit threshold without approval", "ir": "transfer-approval-threshold"},
    {"id": "expedite-approval-threshold", "text": "no committed expedite above the cost threshold without approval", "ir": "expedite-approval-threshold"},
    {"id": "high-priority-reschedule-approval", "text": "no committed reschedule of a HIGH-priority work order without approval", "ir": "high-priority-reschedule-approval"},
    {"id": "no-effect-without-approval", "text": "an operation whose business rules require approval commits no effect before a valid approval", "ir": "no-effect-without-approval"},
    {"id": "idempotency-key-unique", "text": "one idempotency key identifies one intent; replays return the first result and cause no second effect", "ir": "idempotency-key-unique"},
]
EXCLUDED_CONSTRAINTS = {
    "decision-status-vocabulary": "control-plane Decision record", "reconciliation-state-vocabulary": "control-plane Outcome record",
    "action-execution-quantity-positive": "control-plane ActionExecution record (covered by quantity-positive-int)",
    "decision-content-immutable": "control-plane provenance (H27)"}
