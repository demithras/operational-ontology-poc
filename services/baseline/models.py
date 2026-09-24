"""Baseline DecisionRecord — same role as
services/decision_service/models.py's DecisionRecord (built up once through
propose(), written once at the end), minus the ontology/shape-specific
fields this variant has no equivalent of. Reuses
services/decision_service/authz.AuthzResult and
services/decision_service/policy.PolicyEvalResult UNCHANGED (both are
already storage-agnostic dataclasses — see services/baseline/propose_flow.py
for why reusing authz.py/policy.py themselves, not just their result types,
is this phase's central fairness decision)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.decision_service.authz import AuthzResult
from services.decision_service.evidence import EvidenceResult
from services.decision_service.policy import PolicyEvalResult

DRAFT = "DRAFT"
PROPOSED = "PROPOSED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
DENIED_AUTHORIZATION = "DENIED_AUTHORIZATION"
DENIED_POLICY = "DENIED_POLICY"
GATE_UNAVAILABLE = "GATE_UNAVAILABLE"
REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
APPROVED = "APPROVED"
ACTION_VERSION_INVALIDATED = "ACTION_VERSION_INVALIDATED"


@dataclass
class DecisionRecord:
    decision_id: str
    decision_type: str
    actor_type: str
    actor_id: str
    action_type: str
    action_version: int
    parameters: dict[str, Any]
    context: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = DRAFT
    principal_actor_id: str | None = None

    authorization_model_version: str = ""
    policy_bundle_version: str = ""
    identity_mapping_version: str = ""
    openfga_authorization_model_id: str | None = None

    evidence: EvidenceResult | None = None
    evidence_snapshot_id: str = ""

    authz_result: AuthzResult | None = None
    policy_result: PolicyEvalResult | None = None

    decision_content_hash: str | None = None
    unavailable_gate: str | None = None

    action_pinned_sha256: str | None = None
    action_version_dir: str = "v1"

    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_decision_hash: str | None = None
    approval_scope: str | None = None

    @property
    def concerns_work_order(self) -> str | None:
        if self.action_type == "reschedule_work_order":
            return self.parameters.get("work_order_id")
        return self.parameters.get("work_order") or self.context.get("work_order_id")
