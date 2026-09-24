"""The propose() orchestration itself — docs/experiment/spec/06_decision_and_action_runtime.md
"Proposal algorithm", trust-boundary order from
docs/experiment/spec/04_architecture.md: authenticate -> authorize -> policy
-> evidence/conformance -> persist.

Deviation from the literal pseudocode's ORDER, documented explicitly (see
docs/experiment/implementation-notes.md Phase 5 section): all contract
VERSIONS are captured up front (spec 06's "create PROPOSED(evidence, current
contract versions)" already implies this), evidence is frozen next (closure
check first — INSUFFICIENT_EVIDENCE short-circuits before ever calling
OpenFGA/OPA, consistent with 04's trust-boundary list which places evidence
snapshotting before authorize/policy), then authz, then policy, and the
SHACL-validated RDF4J write happens EXACTLY ONCE at the very end for
whatever terminal status was reached — never once per gate. This is a
deliberate simplification over "write PROPOSED, then update the same
Decision as each gate runs": RDF4J's add-only statement API has no partial
in-place update primitive suited to a decision built up over several HTTP
round-trips, and a single atomic write means an INSUFFICIENT_EVIDENCE/
DENIED_* decision is exactly as complete (all 12 SHACL-required fields) as
an APPROVED one — see H1's completeness requirement.

"authenticate actor" (04/06) has no separate identity-provider step in this
POC — there is no login/session system anywhere in this repository through
Phase 4, and the canonical fixture's `actors:` block only ever declares
role/region ASSIGNMENTS, never credentials. An actor's identity is
accepted as asserted by the caller and enforced entirely through what
OpenFGA does/doesn't grant that principal — see
docs/experiment/implementation-notes.md for the explicit scoping note.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
import psycopg

from services.decision_service import authz, evidence as evidence_mod, hashing, policy as policy_mod, rdf_writer, store
from services.decision_service.action_types import ActionType, get_action_type
from services.decision_service.manifest import content_addressed
from services.decision_service.models import (
    APPROVED,
    DENIED_AUTHORIZATION,
    DENIED_POLICY,
    INSUFFICIENT_EVIDENCE,
    INVALID_CONFORMANCE,
    REQUIRES_APPROVAL,
    DecisionRecord,
)


class MalformedProposal(ValueError):
    """Raised for F01 ('malformed decision -> reject; 0 external effects')
    — never becomes a Decision record at all, HTTP 422."""


@dataclass
class ProposeDeps:
    conn: psycopg.Connection
    rdf4j_client: object
    http_clients: dict[str, httpx.Client]
    openfga_api_url: str
    openfga_store_id: str | None
    opa_base_url: str
    manifest: dict


def validate_and_load_action(action_type_name: str, parameters: dict) -> ActionType:
    action = get_action_type(action_type_name)
    if action is None:
        raise MalformedProposal(f"unknown action_type {action_type_name!r}")
    missing = [k for k in action.required_parameters if k not in parameters]
    if missing:
        raise MalformedProposal(f"missing required parameters: {missing}")
    if action.name == "transfer_inventory":
        if parameters["source_warehouse"] == parameters["destination_warehouse"]:
            raise MalformedProposal("source and destination warehouse must differ")
        if parameters["quantity"] < 1:
            raise MalformedProposal("quantity must be >= 1")
    if action.name == "expedite_purchase_order" and parameters["expedite_fee"] < 0:
        raise MalformedProposal("expedite_fee must be >= 0")
    return action


def propose(
    deps: ProposeDeps,
    actor_type: str,
    actor_id: str,
    action_type_name: str,
    parameters: dict,
    context: dict,
    force_invalid_conformance: bool = False,
) -> DecisionRecord:
    action = validate_and_load_action(action_type_name, parameters)
    manifest = deps.manifest

    record = DecisionRecord(
        decision_id=f"D-{uuid.uuid4().hex[:20]}",
        decision_type=action.name,
        actor_type=actor_type,
        actor_id=actor_id,
        action_type=action.name,
        action_version=action.version,
        action_pinned_sha256=manifest["actions"][action.name]["sha256"],
        parameters=parameters,
        context=context,
        ontology_version=content_addressed(manifest["ontology"]),
        shape_set_version=content_addressed(manifest["shapes"]),
        authorization_model_version=content_addressed(manifest["openfga"]),
        policy_bundle_version=content_addressed(manifest["opa"]),
        evidence_snapshot_id=f"ES-{uuid.uuid4().hex[:20]}",
    )

    if actor_type == "agent" and deps.openfga_store_id:
        record.principal_actor_id = authz.resolve_principal(deps.openfga_api_url, deps.openfga_store_id, actor_id)

    # --- Evidence + closed-world closure (H14, F02, F08) ---
    ev = evidence_mod.gather_evidence(action, parameters, context, deps.conn, deps.rdf4j_client, deps.http_clients)
    record.evidence = ev
    if not ev.sufficient:
        record.status = INSUFFICIENT_EVIDENCE
        return _finalize(deps, record, force_invalid_conformance)

    # --- Authorization (F03/F04/F23) ---
    if deps.openfga_store_id is None:
        record.authz_result = authz.AuthzResult(
            outcome=authz.UNAVAILABLE, relation=action.authorization_relation, object="?",
            detail="OpenFGA store not resolved (F23: fail closed)",
        )
    else:
        object_ref = authz.resolve_object(action, parameters, ev)
        record.authz_result = authz.check(
            deps.openfga_api_url, deps.openfga_store_id, action.authorization_relation, object_ref, actor_type, actor_id,
        )
    if not record.authz_result.allowed:
        record.status = DENIED_AUTHORIZATION
        return _finalize(deps, record, force_invalid_conformance)

    # --- Protected-transfer authorization (Phase 6 step 0) ---
    # Only reachable once the base check above already ALLOWED — see
    # authz.check_high_priority_protection's docstring and
    # docs/adr/0003-protected-high-priority-transfer-authorization.md.
    protected_deny = authz.check_high_priority_protection(
        action, parameters, ev, deps.openfga_api_url, deps.openfga_store_id, actor_type, actor_id,
    )
    if protected_deny is not None:
        record.authz_result = protected_deny
        record.status = DENIED_AUTHORIZATION
        return _finalize(deps, record, force_invalid_conformance)

    # --- Policy (F05/F06/F24) ---
    input_json = policy_mod.build_input(action, parameters, ev)
    record.policy_result = policy_mod.evaluate(deps.opa_base_url, action, input_json)
    if record.policy_result.outcome in (policy_mod.DENY, policy_mod.UNAVAILABLE):
        record.status = DENIED_POLICY
        return _finalize(deps, record, force_invalid_conformance)

    record.decision_content_hash = hashing.decision_content_hash(
        record.actor_type, record.actor_id, record.principal_actor_id, record.evidence_snapshot_id,
        record.ontology_version, record.shape_set_version, record.authorization_model_version,
        record.policy_bundle_version, record.action_type, record.action_version, record.parameters,
    )

    if record.policy_result.outcome == policy_mod.REQUIRE_APPROVAL:
        record.status = REQUIRES_APPROVAL
    else:
        record.status = APPROVED

    return _finalize(deps, record, force_invalid_conformance)


def _finalize(deps: ProposeDeps, record: DecisionRecord, force_invalid_conformance: bool) -> DecisionRecord:
    # Set BEFORE the first write, not after: the RDF graph is built and sent
    # from `record` as it stands AT WRITE TIME — setting conformance_outcome
    # only on the success branch AFTER write_decision() returned meant the
    # committed graph itself never carried a oo:ConformanceCheck resource at
    # all for the (overwhelmingly common) CONFORMS case, even though the
    # Postgres index and the HTTP response both showed it correctly. Caught
    # by tests/integration/test_forensic_queries.py querying RDF4J directly
    # (H13 query 1) and finding no conformanceOutcome binding.
    if record.conformance_outcome is None:
        record.conformance_outcome = "CONFORMS"

    committed, detail = rdf_writer.write_decision(
        deps.rdf4j_client, _poisoned(record) if force_invalid_conformance else record
    )
    if not committed:
        record.status = INVALID_CONFORMANCE
        record.conformance_outcome = "VIOLATED"
        record.conformance_violations = [detail]
        record.decision_content_hash = None
        record.approved_by = None
        committed2, detail2 = rdf_writer.write_decision(deps.rdf4j_client, record)
        if not committed2:
            raise RuntimeError(f"decision could not be persisted even as INVALID_CONFORMANCE: {detail2}")

    store.insert_decision(deps.conn, record)
    return record


def _poisoned(record: DecisionRecord) -> DecisionRecord:
    """TEST-MODE-ONLY hook (services/decision_service/app.py only calls
    propose() with force_invalid_conformance=True when OO_TEST_MODE=1 and
    the caller explicitly asked for it via context) proving F07 is
    reachable end-to-end through the real HTTP API, not only via the
    standalone SHACL fixtures in tests/contracts/shacl/: sets `oo:status` to
    a URI outside decision-shape.ttl's `sh:in` enumeration, guaranteeing the
    RDF4J write 409s, then lets the real _finalize() fallback path record
    the resulting INVALID_CONFORMANCE decision exactly as it would for a
    genuine bug."""
    import copy

    poisoned = copy.copy(record)
    poisoned.status = "NOT_A_REAL_STATUS"  # not in oo:DecisionStatusScheme -> sh:in violation
    return poisoned
