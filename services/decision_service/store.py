"""Postgres index for decisions — docs/experiment/spec/06: "the Postgres row
is only an index" of the RDF4J-authoritative record. All queries here are
psycopg PARAMETERIZED statements (never string-interpolated SQL), so this
module carries none of the F31 injection risk that motivated
services/common/sparql_escape.py for the SPARQL side.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from services.common.rdf_graphs import decision_graph_iri
from services.decision_service.hashing import evidence_snapshot_content_hash
from services.decision_service.models import DecisionRecord

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def apply_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text())
    conn.commit()


def insert_decision(conn: psycopg.Connection, record: DecisionRecord) -> None:
    evidence = record.evidence
    evidence_snapshot = {}
    if evidence is not None:
        evidence_snapshot = {
            "content_hash": evidence_snapshot_content_hash(
                evidence.facts_used, evidence.source_positions, evidence.projection_row_hashes
            ),
            "observed_at": evidence.observed_at.isoformat(),
            "facts_used": evidence.facts_used,
            "facts_excluded": evidence.facts_excluded,
            "source_positions": evidence.source_positions,
            "missing": evidence.missing,
        }
    authz_json = None
    if record.authz_result is not None:
        authz_json = {
            "outcome": record.authz_result.outcome,
            "relation": record.authz_result.relation,
            "object": record.authz_result.object,
            "checked_at": record.authz_result.checked_at.isoformat(),
            "detail": record.authz_result.detail,
        }
    policy_json = None
    if record.policy_result is not None:
        policy_json = {
            "outcome": record.policy_result.outcome,
            "reasons": record.policy_result.reasons,
            "obligations": record.policy_result.obligations,
            "input_hash": record.policy_result.input_hash,
            "input_json": record.policy_result.input_json,
            "evaluated_at": record.policy_result.evaluated_at.isoformat(),
            "detail": record.policy_result.detail,
        }
    conformance_json = None
    if record.conformance_outcome is not None:
        conformance_json = {"outcome": record.conformance_outcome, "violations": record.conformance_violations}

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO decisions (
                decision_id, decision_type, actor_type, actor_id, principal_actor_id,
                action_type, action_version, parameters, context, status,
                ontology_version, shape_set_version, authorization_model_version, policy_bundle_version,
                decision_content_hash, action_pinned_sha256, action_version_dir, evidence_snapshot_id, evidence_snapshot,
                authorization_result, policy_result, conformance_result,
                approved_by, approved_at, approval_decision_hash, approval_scope,
                rdf_graph, created_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s
            )
            """,
            (
                record.decision_id, record.decision_type, record.actor_type, record.actor_id, record.principal_actor_id,
                record.action_type, record.action_version, json.dumps(record.parameters), json.dumps(record.context), record.status,
                record.ontology_version, record.shape_set_version, record.authorization_model_version, record.policy_bundle_version,
                record.decision_content_hash, record.action_pinned_sha256, record.action_version_dir, record.evidence_snapshot_id, json.dumps(evidence_snapshot),
                json.dumps(authz_json) if authz_json else None,
                json.dumps(policy_json) if policy_json else None,
                json.dumps(conformance_json) if conformance_json else None,
                record.approved_by, record.approved_at, record.approval_decision_hash, record.approval_scope,
                decision_graph_iri(record.decision_id), record.created_at,
            ),
        )
    conn.commit()


def get_decision(conn: psycopg.Connection, decision_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM decisions WHERE decision_id = %s", (decision_id,))
        return cur.fetchone()


def update_approval(
    conn: psycopg.Connection,
    decision_id: str,
    approved_by: str,
    approved_at,
    approval_decision_hash: str,
    approval_scope: str,
    new_status: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE decisions
            SET approved_by = %s, approved_at = %s, approval_decision_hash = %s,
                approval_scope = %s, status = %s, updated_at = now()
            WHERE decision_id = %s
            """,
            (approved_by, approved_at, approval_decision_hash, approval_scope, new_status, decision_id),
        )
    conn.commit()


def update_status(conn: psycopg.Connection, decision_id: str, new_status: str) -> None:
    """Phase 6: services/action_worker/activities.py and
    services/reconciliation both transition a Decision's status
    (APPROVED -> EXECUTING -> a terminal execution/outcome status) via an
    RDF4J SPARQL UPDATE (services/common/action_rdf.py) — this keeps the
    Postgres INDEX row (docs/experiment/spec/06: 'the Postgres row is only
    an index') in sync, exactly like update_approval() above already does
    for the REQUIRES_APPROVAL -> APPROVED transition. Without this,
    `GET /decisions/{id}` (which reads Postgres, never RDF4J directly)
    would show a permanently stale APPROVED status forever after execute()."""
    with conn.cursor() as cur:
        cur.execute("UPDATE decisions SET status = %s, updated_at = now() WHERE decision_id = %s", (new_status, decision_id))
    conn.commit()


def record_proposal_attempt_failure(
    conn: psycopg.Connection, action_type: str, actor_type: str, actor_id: str, reason: str, detail: str | None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO proposal_attempt_failures (action_type, actor_type, actor_id, reason, detail) "
            "VALUES (%s, %s, %s, %s, %s)",
            (action_type, actor_type, actor_id, reason, detail),
        )
    conn.commit()
