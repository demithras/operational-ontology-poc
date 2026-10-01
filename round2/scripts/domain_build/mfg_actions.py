"""Manufacturing: the three governed Actions and the hard/soft Constraints."""
from __future__ import annotations

from .common import I, param, ref

A3 = "contracts/actions/v3/"
XFER_AUTH = ["transfer-inventory-planner", "transfer-inventory-junior-planner", "transfer-inventory-agent-grant"]


def add_actions(b):
    b.action(
        "transfer_inventory",
        [param("source_warehouse", ref("Warehouse")), param("destination_warehouse", ref("Warehouse")), param("part", ref("Part")),
         param("quantity", I), param("work_order", ref("WorkOrder"), False)],
        XFER_AUTH + ["approve-large-transfer-senior-approver", "mitigate-high-priority-planner", "mitigate-high-priority-supervisor"],
        ["transfer_inventory_hard_deny", "transfer_inventory_needs_approval", "transfer_inventory_allow"],
        ["quantity >= 1", "source != destination", "source_available >= quantity"],
        [{"target": "WMS", "operation": "external_call", "fields": ["destination", "part", "quantity", "source"]}],
        "required",
        "WMS_CDC observation within PT30S: the WmsTransferRecord correlated by action_execution_id has status COMMITTED and actual_quantity == requested_quantity (source.available decreases by quantity; destination.available increases by quantity)",
        None, "v3",
        src=f"{A3}transfer_inventory.yaml; contracts/reconciliation/v1/predicates.yaml (exact_success); services/wms/schemas.py (TransferRequest)",
        note="`quantity >= 1` is parameters.quantity.min; effect fields are the WMS TransferRequest fields; compensation: see decisions")
    b.action(
        "expedite_purchase_order",
        [param("po_id", ref("PurchaseOrder")), param("expedite_fee", I)],
        XFER_AUTH + ["approve-large-transfer-supervisor"],
        ["expedite_purchase_order_hard_deny", "expedite_purchase_order_needs_approval", "expedite_purchase_order_allow"],
        ["expedite_fee >= 0", "po_status not in [RECEIVED, CANCELLED]"],
        [{"target": "ERP", "operation": "external_call", "fields": ["expedite_fee"]}],
        "required",
        "ERP_CDC observation within PT30S: purchase_order.expected_at decreases",
        None, "v1",
        src=f"{A3}expedite_purchase_order.yaml; services/action_worker/activities.py (ERP expedite call body)",
        note="authorization.relation is can_transfer_inventory bound to po_id (as written in the contract); compensation.mode manual_recovery_required -> compensation_action null")
    b.action(
        "reschedule_work_order",
        [param("work_order_id", ref("WorkOrder")), param("new_planned_start", I)],
        XFER_AUTH + ["approve-large-transfer-supervisor"],
        ["reschedule_work_order_hard_deny", "reschedule_work_order_needs_approval", "reschedule_work_order_allow"],
        ["work_order_status not in [DONE, CANCELLED]"],
        [{"target": "MES", "operation": "external_call", "fields": ["new_planned_start"]}],
        "required",
        "MES_CDC observation within PT30S: work_order.planned_start changes to new_planned_start",
        "reschedule_work_order", "v1",
        src=f"{A3}reschedule_work_order.yaml; services/action_worker/activities.py (MES reschedule call body)",
        note="compensation.mode compensatable with operation reschedule_work_order -> the action is its own compensation")


def add_constraints(b):
    C = b.constraint
    sh = "contracts/shapes/v3/"
    inv = "reference_model/invariants.py"
    C("inventory-on-hand-nonnegative", "InventoryLot", "shacl:fac:InventoryLotShape#onHand minInclusive 0", "hard", src=f"{sh}fac-core-shape.ttl (InventoryLotShape onHand); services/wms/schema.sql (CHECK on_hand >= 0)")
    C("inventory-reserved-nonnegative", "InventoryLot", "shacl:fac:InventoryLotShape#reserved minInclusive 0", "hard", src=f"{sh}fac-core-shape.ttl (InventoryLotShape reserved)")
    C("inventory-on-hand-covers-reserved", "InventoryLot", "invariant: onHand >= reserved", "hard", src=f"{inv} (check_invariants lot); services/wms/schema.sql (CHECK on_hand_ge_reserved)")
    C("inventory-available-nonnegative", "InventoryLot", "invariant: onHand - reserved >= 0", "hard", src=f"{inv} (check_invariants: available < 0)")
    C("quality-status-vocabulary", "InventoryLot", "enum:OK|QUARANTINE on qualityStatus", "hard", src=f"{inv} (QUALITY_STATUSES); services/wms/schema.sql (CHECK quality_status)")
    C("work-order-status-vocabulary", "WorkOrder", "enum:PLANNED|RELEASED|RUNNING|DONE|CANCELLED on status", "hard", src=f"{inv} (WORK_ORDER_STATUSES); services/mes/schema.sql (CHECK status)")
    C("decision-status-vocabulary", "Decision", "shacl:oo:DecisionShape#status sh:in", "hard", src=f"{sh}decision-shape.ttl (oo:status sh:in)")
    C("reconciliation-state-vocabulary", "Outcome", "shacl:oo:OutcomeShape#reconciliationState sh:in", "hard", src=f"{sh}action-execution-shape.ttl (OutcomeShape)")
    C("action-execution-quantity-positive", "ActionExecution", "shacl:oo:ActionExecutionShape#quantity minInclusive 1", "hard", src=f"{sh}action-execution-shape.ttl (ActionExecutionShape quantity)")
    C("transfer-endpoints-disjoint", "ActionExecution", "shacl:oo:ActionExecutionShape#sourceWarehouse disjoint destinationWarehouse", "hard", src=f"{sh}action-execution-shape.ttl (sh:disjoint)")
    C("idempotency-key-unique", "ActionExecution", "invariant: actionExecutionId applied at most once", "hard", src=f"{inv} (duplicate idempotency keys applied); services/wms/schema.sql (unique action_execution_id)")
    C("decision-content-immutable", "Decision", "invariant: recomputed decision_content_hash equals the stored hash", "hard", src=f"{inv} (content_hash mismatch); contracts/ontology/v3/oo-core.ttl (Decision 'Immutable once APPROVED')")
    C("no-effect-without-approval", "Decision", "invariant: denial/pending statuses carry no execution or outcome", "hard", src=f"{inv} (DECISION_NO_EFFECT_STATUSES)")
    C("transfer-safety-stock", "transfer_inventory", "rego:factory.inventory.transfer_v2#remaining >= safety_stock", "hard", src="contracts/policies/v2/transfer_inventory.rego (hard_deny remaining < safety_stock); contracts/policies/v2/data.json (safety_stock_v2)")
    C("transfer-quarantine-blocked", "transfer_inventory", "rego:factory.inventory.transfer_v2#no QUARANTINE on source or destination", "hard", src="contracts/policies/v2/transfer_inventory.rego (hard_deny QUARANTINE)")
    C("evidence-freshness", "transfer_inventory", "closure.max_evidence_freshness_s <= 5", "hard", src=f"{A3}transfer_inventory.yaml (closure.max_evidence_freshness_s: 5); transfer_inventory.rego (hard_deny STALE)")
    C("transfer-approval-threshold", "transfer_inventory", "quantity <= approval_threshold_units (80) without approval", "soft", src=f"{A3}transfer_inventory.yaml (policy.approval_threshold_units: 80); transfer_inventory.rego (needs_approval)",
      note="soft = a violation routes to require_approval instead of deny")
    C("expedite-approval-threshold", "expedite_purchase_order", "expedite_fee <= approval_threshold_cost (500) without approval", "soft", src=f"{A3}expedite_purchase_order.yaml (policy.approval_threshold_cost: 500); expedite_purchase_order.rego (needs_approval)")
    C("high-priority-reschedule-approval", "reschedule_work_order", "priority != HIGH without approval", "soft", src="contracts/policies/v1/reschedule_work_order.rego (needs_approval when priority == HIGH)")
