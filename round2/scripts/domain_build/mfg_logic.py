"""Manufacturing: Functions (read/compute logic) and Policies/Authority rules."""
from __future__ import annotations

from .common import I, J, S, opt, param, ref

RM = "reference_model"
AZ = "contracts/authorization/v2/model.fga"
POL_T = "contracts/policies/v2/transfer_inventory.rego"
POL_E = "contracts/policies/v1/expedite_purchase_order.rego"
POL_R = "contracts/policies/v1/reschedule_work_order.rego"


def add_functions(b):
    F = b.fn
    F("available_quantity", [param("lot", ref("InventoryLot"))], I, ["InventoryLot.onHand", "InventoryLot.reserved"],
      "reference_model.state:InventoryLot.available",
      src=f"{RM}/state.py (InventoryLot.available = on_hand - reserved); contracts/projections/v2/current_inventory.yaml (COALESCE(rawAvailable, onHand - reserved))",
      note="available = onHand - reserved (fac:availableQuantity is retired since ontology v2)")
    F("incoming_before", [param("part", ref("Part")), param("warehouse", ref("Warehouse")), param("deadline", I)], I,
      ["PurchaseOrder.status", "PurchaseOrder.expectedAt", "PurchaseOrderLine.quantity", "PurchaseOrderLine_purchaseOrder",
       "PartReferencing_part", "PurchaseOrderLine_destinationWarehouse"],
      "reference_model.derive:_incoming_before",
      src=f"{RM}/derive.py (_incoming_before); contracts/projections/v2/work_order_risk.yaml (incoming_purchase_lines)",
      note="sum of pending purchase-order quantity for part into warehouse expected at or before deadline")
    F("work_order_risk", [param("work_order", ref("WorkOrder"))], J,
      ["WorkOrder.status", "WorkOrder.plannedStart", "WorkOrder_warehouse", "BomRequirement.quantity", "BomRequirement_workOrder",
       "BomRequirement_requiresPart", "InventoryLot.onHand", "InventoryLot.reserved", "PurchaseOrder.status", "PurchaseOrder.expectedAt"],
      "reference_model.derive:work_order_risk",
      src=f"{RM}/derive.py (work_order_risk -> WorkOrderRisk{{shortage, at_risk}}); contracts/projections/v2/work_order_risk.yaml",
      note="risk scoring: shortage = max(0, sum(required - available - incoming_before planned start)); at_risk = shortage > 0; output is the {work_order_id, shortage, at_risk} record as json")
    F("recommend_transfer_for_work_order", [param("work_order", ref("WorkOrder"))], opt(J),
      ["WorkOrder", "InventoryLot", "Warehouse", "BomRequirement"],
      "services.decision_service.planner:recommend_transfer_for_work_order",
      src="services/decision_service/planner.py (recommend_transfer_for_work_order)",
      note="candidate derivation: reads the work_order_risk / transfer_candidates hot projections (derived from these object types); returns a propose-request-shaped record or nothing; deterministic rule, no LLM (H10)")
    F("decision_content_hash", [param("decision", ref("Decision"))], S,
      ["Decision.decisionType", "Decision.ontologyVersion", "Decision.shapeSetVersion", "Decision.authorizationModelVersion",
       "Decision.policyBundleVersion", "Decision.actionType", "Decision.actionVersion", "Decision.parametersJson",
       "Decision_actor", "Decision_evidenceSnapshot"],
      "services.decision_service.hashing:decision_content_hash",
      src="services/decision_service/hashing.py (decision_content_hash); reference_model/transitions.py (compute_pinned_hash)",
      note="sha256 over the pinned (immutable-once-approved) Decision fields only")
    F("resolve_canonical_id", [param("source_local_id", S)], opt(S), ["IdentityMapping.sourceLocalId", "IdentityMapping_canonicalId"],
      "reference_model.transitions:resolve_id", src=f"{RM}/transitions.py (resolve_id, add_id_mapping); contracts/identity/v1/mapping_rules.yaml",
      note="identity resolution: source-local id -> canonical id, nothing when unmapped (F09 quarantines instead of guessing)")


def add_policies(b):
    P = b.policy
    for pid, pkg, ver, src, deny, appr in (
            ("transfer_inventory", "factory.inventory.transfer_v2", "v2", POL_T, "invalid input, STALE evidence, QUARANTINE on source or destination, reservation inconsistent, remaining < safety stock", "quantity > approval_threshold_units"),
            ("expedite_purchase_order", "factory.purchase_order.expedite", "v1", POL_E, "invalid input or terminal purchase order (RECEIVED/CANCELLED)", "expedite_fee > approval_threshold_cost"),
            ("reschedule_work_order", "factory.work_order.reschedule", "v1", POL_R, "invalid input or terminal work order (DONE/CANCELLED)", "priority == HIGH")):
        note = "one Rego package yields several decisions; the IR Policy has ONE decision, so each Rego decision rule is its own Policy"
        P(f"{pid}_hard_deny", "deny", f"rego:{pkg}#hard_deny", ver, src=f"{src} (hard_deny rules: {deny})", note=note)
        P(f"{pid}_needs_approval", "require_approval", f"rego:{pkg}#needs_approval", ver, src=f"{src} (needs_approval: {appr})", note=note)
        P(f"{pid}_allow", "allow", f"rego:{pkg}#allow", ver, src=f"{src} (decision := allow when not hard_deny, not needs_approval, valid_input)", note=note)


def add_authority(b):
    A = b.authority
    t = "action:transfer_inventory"
    A("transfer-inventory-planner", "warehouse#planner", t, "warehouse:*", "allow", False, src=f"{AZ} (can_transfer_inventory: planner; planner from in_region)")
    A("transfer-inventory-junior-planner", "warehouse#junior_planner", t, "warehouse:*", "allow", False, src=f"{AZ} (can_transfer_inventory: junior_planner)")
    A("transfer-inventory-agent-grant", "warehouse#agent_grant", t, "warehouse:*", "allow", True, src=f"{AZ} (can_transfer_inventory: agent_grant; agent type has principal: [user])",
      note="agent acts on behalf of its principal user (oo:actsOnBehalfOf); the only rule marked delegation_allowed (see decisions)")
    A("approve-large-transfer-senior-approver", "warehouse#senior_approver", "approval:large_transfer", "warehouse:*", "allow", False,
      src=f"{AZ} (can_approve_large_transfer_v2: senior_approver, NOT unioned with supervisor); contracts/actions/v3/transfer_inventory.yaml (approval_relation)")
    A("approve-large-transfer-supervisor", "warehouse#supervisor", "approval:large_transfer_v1", "warehouse:*", "allow", False,
      src=f"{AZ} (can_approve_large_transfer: supervisor); contracts/actions/v3/expedite_purchase_order.yaml + reschedule_work_order.yaml (approval_relation)",
      note="the v1 approval relation still pinned by expedite_purchase_order and reschedule_work_order")
    A("mitigate-high-priority-planner", "warehouse#planner", "action:mitigate_high_priority", "warehouse:*", "allow", False,
      src=f"{AZ} (can_mitigate_high_priority: planner); contracts/actions/v3/transfer_inventory.yaml (protected_relation)")
    A("mitigate-high-priority-supervisor", "warehouse#supervisor", "action:mitigate_high_priority", "warehouse:*", "allow", False,
      src=f"{AZ} (can_mitigate_high_priority: supervisor)")
