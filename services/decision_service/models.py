"""Shared in-flight decision record — built up incrementally through
services/decision_service/app.py's propose() pipeline, then passed once,
fully formed, to rdf_writer.py (the single SHACL-validated RDF4J write) and
store.py (the Postgres index row). Never partially written — see
docs/experiment/implementation-notes.md Phase 5 section "why the RDF write
happens exactly once, at the end" for the reasoning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.decision_service.authz import AuthzResult
from services.decision_service.evidence import EvidenceResult
from services.decision_service.policy import PolicyEvalResult

# Decision.status values — must match contracts/ontology/v1/oo-core.ttl's
# oo:DecisionStatusScheme notations exactly (contracts/shapes/v1/
# decision-shape.ttl's sh:in enumeration is the enforced source of truth).
DRAFT = "DRAFT"
PROPOSED = "PROPOSED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
DENIED_AUTHORIZATION = "DENIED_AUTHORIZATION"
DENIED_POLICY = "DENIED_POLICY"
INVALID_CONFORMANCE = "INVALID_CONFORMANCE"
REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
APPROVED = "APPROVED"
# Phase 6b / F34 — set by services/action_worker/activities.py at execute()
# time, never by propose_flow.py itself.
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

    ontology_version: str = ""
    shape_set_version: str = ""
    authorization_model_version: str = ""
    policy_bundle_version: str = ""

    evidence: EvidenceResult | None = None
    evidence_snapshot_id: str = ""

    authz_result: AuthzResult | None = None
    policy_result: PolicyEvalResult | None = None

    conformance_outcome: str | None = None
    conformance_violations: list[str] = field(default_factory=list)

    decision_content_hash: str | None = None

    # Phase 6b / F34: the ActionType's contract sha256 pinned at propose()
    # time (contracts/manifests/current.json, via ProposeDeps.manifest) —
    # services/action_worker/activities.py re-verifies this against a FRESH
    # on-disk hash at execute() time.
    action_pinned_sha256: str | None = None

    approved_by: str | None = None
    approved_at: datetime | None = None
    approval_decision_hash: str | None = None
    approval_scope: str | None = None

    @property
    def concerns_warehouse_pair(self) -> tuple[str | None, str | None]:
        if self.action_type == "transfer_inventory":
            return self.parameters.get("source_warehouse"), self.parameters.get("destination_warehouse")
        return None, None

    @property
    def concerns_part(self) -> str | None:
        return self.parameters.get("part")

    @property
    def concerns_work_order(self) -> str | None:
        if self.action_type == "reschedule_work_order":
            return self.parameters.get("work_order_id")
        # Phase 6 step 0: parameters.work_order is the canonical,
        # hash-covered path (contracts/actions/v1/transfer_inventory.yaml) —
        # context.work_order_id is still accepted for backward
        # compatibility (see services/decision_service/evidence.py).
        return self.parameters.get("work_order") or self.context.get("work_order_id")
