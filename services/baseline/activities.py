"""Temporal activities for services/baseline's action worker — same THREE-
activity shape as services/action_worker/activities.py (verify_and_start /
call_external_action / observe_and_finalize), registered under the SAME
name strings so both variants can run the literal same
services/action_worker/workflows.py::ActionExecutionWorkflow class (see
services/baseline/worker.py) — this phase's fairness choice for "SAME
Temporal execution pattern" (spec 10).

Reuses, unmodified: services/action_worker/outcome_eval.py (pure outcome
predicate — no RDF dependency) and the exact same WMS/ERP/MES HTTP call
shapes services/action_worker/activities.py uses (same idempotency key,
same request bodies) — this variant's `call_external_action` is doing
LITERALLY the same external interaction, just resolving the WMS-local part
id via its own relational identity_mapping table instead of a SPARQL
lookup.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from services.action_worker import outcome_eval
from services.baseline import identity, store
from services.baseline.config import BaselineConfig
from services.common.db import get_conn
from services.decision_service.action_types import actions_dir, get_action_type

_TERMINAL_NON_EXECUTABLE = {
    "DRAFT", "PROPOSED", "INSUFFICIENT_EVIDENCE", "DENIED_AUTHORIZATION",
    "DENIED_POLICY", "GATE_UNAVAILABLE", "REQUIRES_APPROVAL",
}


def _current_action_sha256(action_type_name: str, action_version_dir: str) -> str:
    return hashlib.sha256((actions_dir(action_version_dir) / f"{action_type_name}.yaml").read_bytes()).hexdigest()


def _poll_wms_transfer_record(conn, action_execution_id: str, timeout_s: float) -> dict | None:
    """Same polling shape as services/action_worker/activities.py's
    `_poll_wms_transfer_record` — the CDC-observed row
    (services/baseline/consumer.py writes it into `wms_transfer_records`,
    fed by the SAME wms.transfers Debezium topic), NEVER a live WMS
    re-query (H3/H12)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        activity.heartbeat("polling for CDC-observed WMS transfer record")
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, requested_quantity, actual_quantity FROM wms_transfer_records WHERE action_execution_id = %s",
                (action_execution_id,),
            )
            row = cur.fetchone()
        if row is not None:
            return {"status": row[0], "requested_quantity": row[1], "actual_quantity": row[2]}
        time.sleep(1.0)
    return None


class BaselineActionActivities:
    def __init__(self, config: BaselineConfig):
        self.config = config

    @activity.defn(name="verify_and_start_execution")
    def verify_and_start_execution(self, decision_id: str, action_execution_id: str) -> dict[str, Any]:
        with get_conn() as conn:
            row = store.get_decision(conn, decision_id)
        if row is None:
            raise ApplicationError(f"decision {decision_id!r} not found", non_retryable=True)
        if row["status"] in _TERMINAL_NON_EXECUTABLE:
            raise ApplicationError(f"decision {decision_id!r} is not executable (status={row['status']!r})", non_retryable=True)
        if row["decision_content_hash"] is None:
            raise ApplicationError(f"decision {decision_id!r} has no decision_content_hash", non_retryable=True)

        action_version_dir = row.get("action_version_dir") or "v1"
        pinned_sha256 = row.get("action_pinned_sha256")
        if pinned_sha256 is not None:
            current_sha256 = _current_action_sha256(row["action_type"], action_version_dir)
            if current_sha256 != pinned_sha256:
                with get_conn() as conn:
                    store.update_status(conn, decision_id, "ACTION_VERSION_INVALIDATED")
                raise ApplicationError(
                    f"decision {decision_id!r} pinned action {row['action_type']!r} sha256={pinned_sha256!r} but "
                    f"current is sha256={current_sha256!r} (F34) — invalidated, never executed",
                    non_retryable=True,
                )

        action = get_action_type(row["action_type"], action_version_dir)
        with get_conn() as conn:
            store.insert_action_execution(
                conn, action_execution_id, decision_id,
                external_system=action.raw["external_operation"]["system"],
                external_operation=action.raw["external_operation"]["operation"],
                temporal_workflow_id=activity.info().workflow_id,
                started_at=datetime.now(timezone.utc),
            )
            store.update_status(conn, decision_id, "EXECUTING")

        return {
            "decision_id": decision_id, "action_type": row["action_type"], "action_version": row["action_version"],
            "parameters": row["parameters"], "actor_id": row["actor_id"],
        }

    @activity.defn(name="call_external_action")
    def call_external_action(self, action_execution_id: str, action_type: str, parameters: dict) -> dict[str, Any]:
        before: dict[str, Any] = {}
        if action_type == "transfer_inventory":
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT on_hand, reserved FROM inventory_lots WHERE part = %s AND warehouse_id = %s", (parameters["part"], parameters["source_warehouse"]))
                    src = cur.fetchone()
                    cur.execute("SELECT on_hand, reserved FROM inventory_lots WHERE part = %s AND warehouse_id = %s", (parameters["part"], parameters["destination_warehouse"]))
                    dst = cur.fetchone()
                wms_local_part = identity.reverse_lookup(conn, parameters["part"], "WMS")
            before["source_available_before"] = (src[0] - src[1]) if src else 0
            before["destination_available_before"] = (dst[0] - dst[1]) if dst else 0
            if wms_local_part is None:
                raise ApplicationError(f"no WMS identity mapping found for canonical part {parameters['part']!r}", non_retryable=True)
            with httpx.Client(base_url=self.config.wms_base_url, timeout=10.0) as wms:
                resp = wms.post(
                    "/transfers",
                    json={
                        "action_execution_id": action_execution_id, "source": parameters["source_warehouse"],
                        "destination": parameters["destination_warehouse"], "part": wms_local_part, "quantity": parameters["quantity"],
                    },
                )
        elif action_type == "expedite_purchase_order":
            with httpx.Client(base_url=self.config.erp_base_url, timeout=10.0) as erp:
                resp = erp.post(f"/purchase_orders/{parameters['po_id']}/expedite", json={"action_execution_id": action_execution_id, "expedite_fee": parameters.get("expedite_fee", 0)})
        elif action_type == "reschedule_work_order":
            with httpx.Client(base_url=self.config.mes_base_url, timeout=10.0) as mes:
                resp = mes.post(f"/work_orders/{parameters['work_order_id']}/reschedule", json={"action_execution_id": action_execution_id, "new_planned_start": parameters["new_planned_start"]})
        else:
            raise ApplicationError(f"no external dispatcher for action_type {action_type!r}", non_retryable=True)

        try:
            body = resp.json()
        except ValueError:
            body = {"raw_text": resp.text[:2000]}
        return {"http_status": resp.status_code, "body": body, **before}

    @activity.defn(name="observe_and_finalize")
    def observe_and_finalize(self, decision_id: str, action_execution_id: str, action_type: str, parameters: dict, actor_id: str, command_result: dict) -> dict[str, Any]:
        action = get_action_type(action_type)
        observation_timeout_s = 30.0

        if action_type == "transfer_inventory":
            if command_result["http_status"] not in (200, 409):
                verdict = outcome_eval.OutcomeVerdict(outcome_eval.OUTCOME_UNKNOWN, {}, command_result, f"unexpected WMS command HTTP status {command_result['http_status']}")
            else:
                with get_conn() as conn:
                    transfer_record = _poll_wms_transfer_record(conn, action_execution_id, observation_timeout_s)
                verdict = outcome_eval.evaluate_transfer_outcome(
                    parameters["quantity"], command_result.get("source_available_before", 0),
                    command_result.get("destination_available_before", 0), transfer_record,
                )
        else:
            verdict = outcome_eval.evaluate_command_response_outcome(action_type, command_result["http_status"], command_result["body"])

        compensation_status = "NOT_APPLICABLE"
        compensating_action_execution_id = None
        if verdict.status == outcome_eval.DIVERGED and action_type == "transfer_inventory" and action.compensation_mode == "compensatable":
            compensating_action_execution_id = f"{action_execution_id}-reverse"
            with httpx.Client(base_url=self.config.wms_base_url, timeout=10.0) as wms:
                rresp = wms.post(f"/transfers/{action_execution_id}/reverse", json={"action_execution_id": compensating_action_execution_id})
            compensation_status = "COMPENSATED" if rresp.status_code == 200 else "COMPENSATION_FAILED"
        elif verdict.status == outcome_eval.DIVERGED:
            compensation_status = "MANUAL_RECOVERY_REQUIRED"

        reconciliation_state = {
            outcome_eval.OBSERVED_SUCCESS: "CONVERGED",
            outcome_eval.DIVERGED: "COMPENSATED" if compensation_status == "COMPENSATED" else "DIVERGED",
            outcome_eval.OUTCOME_UNKNOWN: "AWAITING_OBSERVATION",
            outcome_eval.EXECUTION_FAILED: "FAILED",
        }[verdict.status]

        completed_at = datetime.now(timezone.utc)
        with get_conn() as conn:
            store.finalize_action_execution(conn, action_execution_id, str(command_result.get("http_status")), command_result.get("body", {}), completed_at, verdict.status)
            store.insert_outcome(
                conn, f"O-{action_execution_id}", action_execution_id, reconciliation_state,
                verdict.expected_effect, verdict.observed_effect, completed_at, compensation_status, compensating_action_execution_id,
            )
            store.update_status(conn, decision_id, verdict.status)

        return {"decision_id": decision_id, "action_execution_id": action_execution_id, "status": verdict.status, "reason": verdict.reason, "compensation_status": compensation_status}
