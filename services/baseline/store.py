"""Postgres persistence for the baseline decision service — the "well-
designed relational audit table" the brief asks for (services/baseline/
schema.sql). Unlike services/decision_service/store.py (an index over an
RDF4J-authoritative record), THIS is the sole, authoritative record — no
second storage system behind it.
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from services.baseline.hashing import evidence_snapshot_content_hash
from services.baseline.models import DecisionRecord

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
            "content_hash": evidence_snapshot_content_hash(evidence.facts_used, evidence.source_positions, evidence.projection_row_hashes),
            "observed_at": evidence.observed_at.isoformat(),
            "facts_used": evidence.facts_used,
            "facts_excluded": evidence.facts_excluded,
            "source_positions": evidence.source_positions,
            "projection_row_hashes": evidence.projection_row_hashes,
            "missing": evidence.missing,
        }

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO decisions (
                decision_id, decision_type, actor_type, actor_id, principal_actor_id,
                action_type, action_version, action_version_dir, action_pinned_sha256,
                parameters, context, status,
                authorization_model_version, policy_bundle_version, identity_mapping_version,
                openfga_authorization_model_id,
                evidence_snapshot_id, evidence_snapshot,
                decision_content_hash, unavailable_gate,
                approved_by, approved_at, approval_decision_hash, approval_scope,
                created_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s,
                %s, %s,
                %s, %s,
                %s, %s, %s, %s,
                %s
            )
            """,
            (
                record.decision_id, record.decision_type, record.actor_type, record.actor_id, record.principal_actor_id,
                record.action_type, record.action_version, record.action_version_dir, record.action_pinned_sha256,
                json.dumps(record.parameters), json.dumps(record.context), record.status,
                record.authorization_model_version, record.policy_bundle_version, record.identity_mapping_version,
                record.openfga_authorization_model_id,
                record.evidence_snapshot_id, json.dumps(evidence_snapshot),
                record.decision_content_hash, record.unavailable_gate,
                record.approved_by, record.approved_at, record.approval_decision_hash, record.approval_scope,
                record.created_at,
            ),
        )

        if record.authz_result is not None:
            cur.execute(
                """
                INSERT INTO gate_results (decision_id, gate_type, outcome, relation_or_package, object_or_input_hash, detail, authorization_model_id, tuples_snapshot, evaluated_at)
                VALUES (%s, 'authorization', %s, %s, %s, %s, %s, %s, %s)
                """,
                (record.decision_id, record.authz_result.outcome, record.authz_result.relation, record.authz_result.object,
                 record.authz_result.detail, record.authz_result.model_id,
                 json.dumps(record.authz_result.tuples_snapshot) if record.authz_result.tuples_snapshot is not None else None,
                 record.authz_result.checked_at),
            )
        if record.policy_result is not None:
            cur.execute(
                """
                INSERT INTO gate_results (decision_id, gate_type, outcome, relation_or_package, object_or_input_hash, detail, reasons, obligations, input_json, evaluated_at)
                VALUES (%s, 'policy', %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (record.decision_id, record.policy_result.outcome, None, record.policy_result.input_hash,
                 record.policy_result.detail, json.dumps(record.policy_result.reasons), json.dumps(record.policy_result.obligations),
                 json.dumps(record.policy_result.input_json), record.policy_result.evaluated_at),
            )
    conn.commit()


def get_decision(conn: psycopg.Connection, decision_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM decisions WHERE decision_id = %s", (decision_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute("SELECT * FROM gate_results WHERE decision_id = %s ORDER BY id", (decision_id,))
        gates = cur.fetchall()
    row["gate_results"] = gates
    row["authorization_result"] = next((g for g in gates if g["gate_type"] == "authorization"), None)
    row["policy_result"] = next((g for g in gates if g["gate_type"] == "policy"), None)
    return row


def update_approval(conn: psycopg.Connection, decision_id: str, approved_by: str, approved_at, approval_decision_hash: str, approval_scope: str, new_status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE decisions SET approved_by = %s, approved_at = %s, approval_decision_hash = %s, approval_scope = %s, status = %s, updated_at = now() WHERE decision_id = %s",
            (approved_by, approved_at, approval_decision_hash, approval_scope, new_status, decision_id),
        )
    conn.commit()


def update_status(conn: psycopg.Connection, decision_id: str, new_status: str) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE decisions SET status = %s, updated_at = now() WHERE decision_id = %s", (new_status, decision_id))
    conn.commit()


def record_proposal_attempt_failure(conn: psycopg.Connection, action_type: str, actor_type: str, actor_id: str, reason: str, detail: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO proposal_attempt_failures (action_type, actor_type, actor_id, reason, detail) VALUES (%s, %s, %s, %s, %s)",
            (action_type, actor_type, actor_id, reason, detail),
        )
    conn.commit()


def insert_action_execution(conn: psycopg.Connection, action_execution_id: str, decision_id: str, external_system: str, external_operation: str, temporal_workflow_id: str, started_at) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO action_executions (action_execution_id, decision_id, external_system, external_operation, temporal_workflow_id, started_at, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'EXECUTING')
            ON CONFLICT (action_execution_id) DO NOTHING
            """,
            (action_execution_id, decision_id, external_system, external_operation, temporal_workflow_id, started_at),
        )
    conn.commit()


def get_action_execution(conn: psycopg.Connection, action_execution_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM action_executions WHERE action_execution_id = %s", (action_execution_id,))
        return cur.fetchone()


def finalize_action_execution(conn: psycopg.Connection, action_execution_id: str, command_status: str, command_receipt: dict, completed_at, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE action_executions SET command_status = %s, command_receipt = %s, completed_at = %s, status = %s WHERE action_execution_id = %s",
            (command_status, json.dumps(command_receipt), completed_at, status, action_execution_id),
        )
    conn.commit()


def insert_outcome(conn: psycopg.Connection, outcome_id: str, action_execution_id: str, reconciliation_state: str, expected_effect: dict, observed_effect: dict, observed_at, compensation_status: str, compensating_action_execution_id: str | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO outcomes (outcome_id, action_execution_id, reconciliation_state, expected_effect, observed_effect, observed_at, compensation_status, compensating_action_execution_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (outcome_id) DO UPDATE SET reconciliation_state = EXCLUDED.reconciliation_state,
                observed_effect = EXCLUDED.observed_effect, observed_at = EXCLUDED.observed_at,
                compensation_status = EXCLUDED.compensation_status
            """,
            (outcome_id, action_execution_id, reconciliation_state, json.dumps(expected_effect), json.dumps(observed_effect), observed_at, compensation_status, compensating_action_execution_id),
        )
    conn.commit()


def get_outcome_by_execution(conn: psycopg.Connection, action_execution_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM outcomes WHERE action_execution_id = %s", (action_execution_id,))
        return cur.fetchone()
