"""The baseline's propose() orchestration — same trust-boundary order as
services/decision_service/propose_flow.py (evidence -> authz -> policy ->
persist), and this phase's central fairness decision: REUSES
services/decision_service/{authz,policy,action_types}.py UNMODIFIED. Those
three modules never touch RDF4J — authz.py/policy.py are plain HTTP clients
for OpenFGA/OPA, action_types.py just parses YAML — so importing them here
means both variants' authorization/policy GATES are the literal same code,
not a reimplementation that could silently drift (spec 10 fairness rule 4:
"Same authorization/policy where applicable"). Only the DECISION RECORD
(this variant is a flat Postgres row set, not a SHACL-validated RDF graph)
and EVIDENCE gathering (services/baseline/evidence.py, reading this
variant's own CDC-fed relational tables) are variant-specific.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx
import psycopg

from services.baseline import evidence as evidence_mod, hashing, store
from services.baseline.manifest import build_baseline_manifest, content_addressed
from services.baseline.models import (
    APPROVED,
    DENIED_AUTHORIZATION,
    DENIED_POLICY,
    GATE_UNAVAILABLE,
    INSUFFICIENT_EVIDENCE,
    REQUIRES_APPROVAL,
    DecisionRecord,
)
from services.decision_service import authz, policy as policy_mod
from services.decision_service.action_types import ActionType, get_action_type


class MalformedProposal(ValueError):
    pass


@dataclass
class ProposeDeps:
    conn: psycopg.Connection
    http_clients: dict[str, httpx.Client]
    openfga_api_url: str
    openfga_store_id: str | None
    opa_base_url: str
    manifest: dict
    openfga_authorization_model_id: str | None = None


def validate_and_load_action(action_type_name: str, parameters: dict, action_version_dir: str = "v1") -> ActionType:
    action = get_action_type(action_type_name, action_version_dir)
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
) -> DecisionRecord:
    manifest = deps.manifest
    action_version_dir = manifest["deployed_version"]["actions"]
    action = validate_and_load_action(action_type_name, parameters, action_version_dir)

    record = DecisionRecord(
        decision_id=f"B-{uuid.uuid4().hex[:20]}",
        decision_type=action.name,
        actor_type=actor_type,
        actor_id=actor_id,
        action_type=action.name,
        action_version=action.version,
        action_pinned_sha256=manifest["actions"][action.name]["sha256"],
        action_version_dir=action_version_dir,
        parameters=parameters,
        context=context,
        authorization_model_version=content_addressed(manifest["openfga"]),
        policy_bundle_version=content_addressed(manifest["opa"]),
        identity_mapping_version=content_addressed(manifest["identity"]),
        openfga_authorization_model_id=deps.openfga_authorization_model_id,
        evidence_snapshot_id=f"ES-{uuid.uuid4().hex[:20]}",
    )

    if actor_type == "agent" and deps.openfga_store_id:
        record.principal_actor_id = authz.resolve_principal(deps.openfga_api_url, deps.openfga_store_id, actor_id)

    ev = evidence_mod.gather_evidence(action, parameters, context, deps.conn, deps.http_clients)
    record.evidence = ev
    if not ev.sufficient:
        record.status = INSUFFICIENT_EVIDENCE
        return _finalize(deps, record)

    if deps.openfga_store_id is None:
        record.authz_result = authz.AuthzResult(
            outcome=authz.UNAVAILABLE, relation=action.authorization_relation, object="?",
            detail="OpenFGA store not resolved (F23: fail closed)",
        )
    else:
        object_ref = authz.resolve_object(action, parameters, ev)
        record.authz_result = authz.check(
            deps.openfga_api_url, deps.openfga_store_id, action.authorization_relation, object_ref, actor_type, actor_id,
            deps.openfga_authorization_model_id,
        )
    if not record.authz_result.allowed:
        if record.authz_result.outcome == authz.UNAVAILABLE:
            record.status = GATE_UNAVAILABLE
            record.unavailable_gate = "authorization"
        else:
            record.status = DENIED_AUTHORIZATION
        return _finalize(deps, record)

    protected_deny = authz.check_high_priority_protection(
        action, parameters, ev, deps.openfga_api_url, deps.openfga_store_id, actor_type, actor_id,
        deps.openfga_authorization_model_id,
    )
    if protected_deny is not None:
        record.authz_result = protected_deny
        if protected_deny.outcome == authz.UNAVAILABLE:
            record.status = GATE_UNAVAILABLE
            record.unavailable_gate = "authorization"
        else:
            record.status = DENIED_AUTHORIZATION
        return _finalize(deps, record)

    input_json = policy_mod.build_input(action, parameters, ev)
    record.policy_result = policy_mod.evaluate(deps.opa_base_url, action, input_json)
    if record.policy_result.outcome == policy_mod.UNAVAILABLE:
        record.status = GATE_UNAVAILABLE
        record.unavailable_gate = "policy"
        return _finalize(deps, record)
    if record.policy_result.outcome == policy_mod.DENY:
        record.status = DENIED_POLICY
        return _finalize(deps, record)

    record.decision_content_hash = hashing.decision_content_hash(
        record.actor_type, record.actor_id, record.principal_actor_id, record.evidence_snapshot_id,
        record.authorization_model_version, record.policy_bundle_version,
        record.action_type, record.action_version, record.parameters,
    )
    record.status = REQUIRES_APPROVAL if record.policy_result.outcome == policy_mod.REQUIRE_APPROVAL else APPROVED
    return _finalize(deps, record)


def _finalize(deps: ProposeDeps, record: DecisionRecord) -> DecisionRecord:
    # No SHACL-equivalent structural gate here — the relational analogue
    # (schema.sql's `status` CHECK constraint) is enforced by Postgres
    # itself at INSERT time; a status this module ever produces is always
    # one of the CHECK's literal values, so there is no INVALID_CONFORMANCE-
    # style fallback path to build (an HONEST architectural gap this phase
    # reports rather than papers over — see docs/experiment/implementation-notes.md
    # Phase 8 section: this variant has no general-purpose "arbitrary state-
    # transition shape" validator the way SHACL is; it only has whatever
    # specific constraints someone thought to hand-write into schema.sql).
    store.insert_decision(deps.conn, record)
    return record
