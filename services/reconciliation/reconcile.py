"""One reconciliation pass — the independent re-check (H12) over decisions
services/action_worker left in OUTCOME_UNKNOWN (its own CDC poll timed out,
F18/F21). Scope decision: EXECUTING decisions are NOT actively driven here
— Temporal's own durable-execution replay is what resolves a crashed
worker's in-flight EXECUTING decision (F12/F13), so reconciliation only
COUNTS them for visibility, never mutates them (mutating a workflow's own
Decision out from under Temporal's replay would race it). Only
transfer_inventory is reconciled here — the documented lighter-scope
ActionTypes (expedite_purchase_order/reschedule_work_order) finalize
synchronously in services/action_worker and never land in OUTCOME_UNKNOWN
at all (see services/action_worker/outcome_eval.py's module docstring).
"""

from __future__ import annotations

import json

import psycopg
from psycopg.rows import dict_row

from services.action_worker import outcome_eval
from services.common.wms_transfer_observation import fetch_wms_transfer_record
from services.common import action_rdf
from services.decision_service.execution import action_execution_id_for
from services.decision_service.execution_reader import get_outcome
from services.decision_service.store import update_status

_RECONCILIATION_STATE_FOR = {
    outcome_eval.OBSERVED_SUCCESS: "CONVERGED",
    outcome_eval.DIVERGED: "DIVERGED",
    outcome_eval.EXECUTION_FAILED: "FAILED",
}


def watched_decisions(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT decision_id, action_type, status FROM decisions "
            "WHERE action_type = 'transfer_inventory' AND status IN ('EXECUTING', 'OUTCOME_UNKNOWN') "
            "ORDER BY created_at"
        )
        return cur.fetchall()


def _record_alert(conn: psycopg.Connection, decision_id: str, action_execution_id: str, expected: dict, observed: dict, compensation_status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reconciliation_alerts (decision_id, action_execution_id, expected_effect_json, observed_effect_json, compensation_status)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (action_execution_id) DO NOTHING
            """,
            (decision_id, action_execution_id, json.dumps(expected), json.dumps(observed), compensation_status),
        )
    conn.commit()


def _record_convergence(conn: psycopg.Connection, decision_id: str, action_execution_id: str, old_state: str, new_state: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reconciliation_convergences (decision_id, action_execution_id, old_reconciliation_state, new_reconciliation_state)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (action_execution_id, new_reconciliation_state) DO NOTHING
            """,
            (decision_id, action_execution_id, old_state, new_state),
        )
    conn.commit()


def reconcile_one(hot_conn: psycopg.Connection, rdf4j_client, decision_row: dict) -> str:
    """Returns a short outcome tag for logging/metrics:
    "watched" (EXECUTING, no action), "no_observation_yet" (still
    AWAITING_OBSERVATION), "converged", "diverged_alert_raised"."""
    decision_id = decision_row["decision_id"]
    if decision_row["status"] == "EXECUTING":
        return "watched"

    action_execution_id = action_execution_id_for(decision_id)
    outcome_id = f"O-{action_execution_id}"
    outcome_row = get_outcome(rdf4j_client, outcome_id)
    if outcome_row is None or outcome_row.get("reconciliationState") != "AWAITING_OBSERVATION":
        return "watched"

    record = fetch_wms_transfer_record(rdf4j_client, action_execution_id)
    if record is None:
        return "no_observation_yet"

    verdict = outcome_eval.evaluate_transfer_outcome(record["requested_quantity"], 0, 0, record)
    if verdict.status == outcome_eval.OUTCOME_UNKNOWN:
        return "no_observation_yet"  # defensive; unreachable when record is not None

    new_reconciliation_state = _RECONCILIATION_STATE_FOR[verdict.status]
    committed, detail = action_rdf.write_reconciliation_state_update(
        rdf4j_client,
        decision_id=decision_id,
        outcome_id=outcome_id,
        old_reconciliation_state="AWAITING_OBSERVATION",
        new_reconciliation_state=new_reconciliation_state,
        decision_final_status=verdict.status,
        decision_from_status="OUTCOME_UNKNOWN",
    )
    if not committed:
        raise RuntimeError(f"reconciliation could not update {decision_id!r}: {detail[:300]}")
    update_status(hot_conn, decision_id, verdict.status)

    _record_convergence(hot_conn, decision_id, action_execution_id, "AWAITING_OBSERVATION", new_reconciliation_state)

    if verdict.status == outcome_eval.DIVERGED:
        # H12: "raise a reconciliation alert record with expected, observed,
        # action/decision, source evidence, retry/compensation status".
        # Compensation is intentionally NOT re-attempted here — only
        # services/action_worker's OWN finalize path compensates, to avoid
        # a double-compensation race between two independent processes
        # acting on the same ActionExecution. This late-detected divergence
        # (CDC arrived only after the worker's own 30s wait expired) is
        # flagged MANUAL_RECOVERY_REQUIRED for a human/later automated pass.
        _record_alert(hot_conn, decision_id, action_execution_id, verdict.expected_effect, verdict.observed_effect, "MANUAL_RECOVERY_REQUIRED")
        return "diverged_alert_raised"
    return "converged"
