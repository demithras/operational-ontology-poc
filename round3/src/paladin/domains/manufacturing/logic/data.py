"""Business configuration ported from the v1 POC (values are cross-checked against the source files in tests).

transfer_inventory v3 -> policy package factory.inventory.transfer_v2:
  contracts/policies/v2/data.json (safety_stock_v2, default_safety_stock_v2)
  contracts/actions/v3/transfer_inventory.yaml (approval_threshold_units, closure.max_evidence_freshness_s)
expedite_purchase_order v1: contracts/actions/v1/expedite_purchase_order.yaml (approval_threshold_cost)
"""
from __future__ import annotations

SAFETY_STOCK_V2 = {("PX-17", "WH-B"): 60, ("PX-800501", "WH-B"): 60}
DEFAULT_SAFETY_STOCK_V2 = 15
APPROVAL_THRESHOLD_UNITS = 80
APPROVAL_THRESHOLD_COST = 500
MAX_EVIDENCE_FRESHNESS_S = 5

TERMINAL_WO = ("DONE", "CANCELLED")
TERMINAL_PO = ("RECEIVED", "CANCELLED")
QUALITY_VOCAB = ("OK", "QUARANTINE")
WORK_ORDER_STATUS_VOCAB = ("PLANNED", "RELEASED", "RUNNING", "DONE", "CANCELLED")
# oo:DecisionStatusScheme notations (contracts/shapes/v3/decision-shape.ttl sh:in; services/decision_service/models.py)
DECISION_STATUS_VOCAB = ("DRAFT", "PROPOSED", "INSUFFICIENT_EVIDENCE", "DENIED_AUTHORIZATION", "DENIED_POLICY",
                         "INVALID_CONFORMANCE", "REQUIRES_APPROVAL", "APPROVED", "EXECUTING", "EXECUTION_FAILED",
                         "OUTCOME_UNKNOWN", "AWAITING_OBSERVATION", "DIVERGED", "OBSERVED_SUCCESS",
                         "ACTION_VERSION_INVALIDATED", "GATE_UNAVAILABLE")
# contracts/shapes/v3/action-execution-shape.ttl OutcomeShape sh:in
RECONCILIATION_VOCAB = ("NOT_STARTED", "COMMAND_SENT", "COMMAND_ACCEPTED", "AWAITING_OBSERVATION", "CONVERGED",
                        "DIVERGED", "OUTCOME_UNKNOWN", "COMPENSATING", "COMPENSATED", "FAILED")
# statuses that must carry no execution or outcome (decision never reached execution)
NO_EFFECT_STATUSES = ("DRAFT", "PROPOSED", "INSUFFICIENT_EVIDENCE", "DENIED_AUTHORIZATION", "DENIED_POLICY",
                      "INVALID_CONFORMANCE", "REQUIRES_APPROVAL", "GATE_UNAVAILABLE")


def safety_stock(part: str, warehouse: str) -> int:
    return SAFETY_STOCK_V2.get((part, warehouse), DEFAULT_SAFETY_STOCK_V2)
