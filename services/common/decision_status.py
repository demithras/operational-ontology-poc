"""Single source of truth for oo:DecisionStatusScheme's status -> concept
IRI mapping (contracts/ontology/v1/oo-core.ttl). Shared by
services/decision_service/rdf_writer.py (Phase 5: DRAFT..APPROVED) and
services/common/action_rdf.py (Phase 6: EXECUTING..OBSERVED_SUCCESS) so the
two phases' RDF writers can never drift on how a status string maps to its
RDF concept.
"""

from __future__ import annotations

OO_NS = "https://example.local/oo/"

STATUS_CONCEPT_LOCAL: dict[str, str] = {
    "DRAFT": "Draft",
    "PROPOSED": "Proposed",
    "INSUFFICIENT_EVIDENCE": "InsufficientEvidence",
    "DENIED_AUTHORIZATION": "DeniedAuthorization",
    "DENIED_POLICY": "DeniedPolicy",
    "INVALID_CONFORMANCE": "InvalidConformance",
    "REQUIRES_APPROVAL": "RequiresApproval",
    "APPROVED": "Approved",
    "EXECUTING": "Executing",
    "EXECUTION_FAILED": "ExecutionFailed",
    "OUTCOME_UNKNOWN": "OutcomeUnknown",
    "AWAITING_OBSERVATION": "AwaitingObservation",
    "DIVERGED": "Diverged",
    "OBSERVED_SUCCESS": "ObservedSuccess",
}


def status_concept_iri(status: str) -> str:
    """Returns the full oo: concept IRI for a status string, or a
    deliberately UNKNOWN (never-in-scheme) IRI for anything not in the v1
    enumeration — matching services/decision_service/rdf_writer.py's
    existing test-mode-poisoning convention: an out-of-scheme URI fails
    decision-shape.ttl's sh:in check loudly (409), rather than the writer
    silently coercing an unrecognized status into something that happens to
    validate."""
    local = STATUS_CONCEPT_LOCAL.get(status, f"UnknownStatus_{status or 'empty'}")
    return f"{OO_NS}{local}"
