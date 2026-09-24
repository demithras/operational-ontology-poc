"""Temporal activities for services/action_worker — the ONLY place real I/O
happens (spec 06 execute()/workflow algorithm's "call external API",
"persist command receipt", "wait for correlated CDC observation"). Plain
SYNCHRONOUS methods (this repo's established style: sync psycopg/httpx
everywhere) — run under a ThreadPoolExecutor via `activity_executor=` on
the Worker (services/action_worker/worker.py).

A CLASS (not free functions) so `config` (RDF4J/WMS/ERP/MES base URLs) is
bound ONCE at Worker-registration time rather than re-serialized as a
Temporal argument on every activity call — the standard temporalio pattern
for activities that close over shared config/clients
(services/action_worker/worker.py does `activities = ActionActivities(config)`
then registers `activities.verify_and_start_execution` etc.).

Idempotency/replay-safety (F12/F13 "worker crash -> resume/recover without
duplicate effect"): every activity here is safe to re-run with the SAME
inputs — verify_and_start_execution's RDF writes are additive-or-no-op
(services/common/action_rdf.py), call_external_action's external POST is
deduped by the SAME action_execution_id at the WMS/ERP/MES boundary
(idempotency key, unique constraint), and observe_and_finalize's RDF write
is the SAME replay-safe pattern. Temporal's own durable execution history
means a crashed worker's in-flight workflow resumes on the NEXT worker
instance from its last COMPLETED activity — this repo's job is only to
make each activity idempotent, not to reimplement durability.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from services.action_worker import outcome_eval
from services.action_worker.config import ActionWorkerConfig
from services.common import action_rdf, test_hooks
from services.common.db import get_conn
from services.common.identity_lookup import resolve_canonical_part_to_source_local
from services.common.rdf4j_client import RDF4JClient
from services.common.wms_transfer_observation import fetch_wms_transfer_record
from services.decision_service.action_types import ACTIONS_DIR, actions_dir, get_action_type
from services.decision_service.store import get_decision, update_status
from services.projection_builder.reader import get_current_inventory

TEST_MODE = os.environ.get("OO_TEST_MODE") == "1"


def _current_action_sha256(action_type_name: str, action_version_dir: str = "v1") -> str:
    """F34: a FRESH sha256 of contracts/actions/<action_version_dir>/<name>.yaml's
    raw bytes, read directly off disk — deliberately NOT via
    services/decision_service/action_types.py::get_action_type, whose
    _REGISTRY is cached for the lifetime of this process and would never
    observe a post-startup file change (exactly the scenario this check
    exists to catch). `action_version_dir` is the decision's OWN recorded
    pin location (Phase 7 — see services/decision_service/models.py's
    action_version_dir field); a decision written before that column
    existed has action_version_dir=None, and the caller passes "v1"
    (every pre-Phase-7 decision was necessarily pinned against
    contracts/actions/v1/)."""
    return hashlib.sha256((actions_dir(action_version_dir) / f"{action_type_name}.yaml").read_bytes()).hexdigest()

_TERMINAL_NON_EXECUTABLE = {
    "DRAFT", "PROPOSED", "INSUFFICIENT_EVIDENCE", "DENIED_AUTHORIZATION",
    "DENIED_POLICY", "INVALID_CONFORMANCE", "REQUIRES_APPROVAL",
}


def _poll_wms_transfer_record(rdf4j_client: RDF4JClient, action_execution_id: str, timeout_s: float) -> dict | None:
    """F18/F21: polls (heartbeating so Temporal knows this activity is
    alive during a long wait) for the CDC-observed fac:WmsTransferRecord
    correlated by action_execution_id — NEVER re-queries WMS live (H3/H12:
    observe reality via CDC, not the command path). Uses the SAME one-shot
    lookup services/reconciliation calls (services/common/wms_transfer_observation.py)
    so the two never define "correlated observation" differently."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        activity.heartbeat("polling for CDC-observed WMS transfer record")
        record = fetch_wms_transfer_record(rdf4j_client, action_execution_id)
        if record is not None:
            return record
        time.sleep(1.0)
    return None


class ActionActivities:
    def __init__(self, config: ActionWorkerConfig):
        self.config = config

    def _rdf4j_client(self) -> RDF4JClient:
        return RDF4JClient(base_url=self.config.rdf4j_base_url, repository=self.config.rdf4j_repository)

    @activity.defn(name="verify_and_start_execution")
    def verify_and_start_execution(self, decision_id: str, action_execution_id: str) -> dict[str, Any]:
        """spec 06 execute(): "load APPROVED decision; verify immutable
        content hash; verify not already terminal/executing incompatibly;
        create ActionExecution". Non-retryable ApplicationError for a
        decision that is provably not executable — retrying that can never
        succeed."""
        with get_conn() as conn:
            row = get_decision(conn, decision_id)
        if row is None:
            raise ApplicationError(f"decision {decision_id!r} not found", non_retryable=True)
        if row["status"] in _TERMINAL_NON_EXECUTABLE:
            raise ApplicationError(
                f"decision {decision_id!r} is not executable (status={row['status']!r})", non_retryable=True,
            )
        if row["decision_content_hash"] is None:
            raise ApplicationError(f"decision {decision_id!r} has no decision_content_hash", non_retryable=True)

        # F34: verify the pinned action-definition version BEFORE ever
        # writing execution-started or calling the external system. Only
        # checked when a pin was actually captured (pre-Phase-6b decisions
        # have none — nothing to compare against, so let those through
        # unchanged rather than retroactively invalidating history).
        pinned_sha256 = row.get("action_pinned_sha256")
        action_version_dir = row.get("action_version_dir") or "v1"
        if pinned_sha256 is not None:
            current_sha256 = _current_action_sha256(row["action_type"], action_version_dir)
            if current_sha256 != pinned_sha256:
                rdf4j_client = self._rdf4j_client()
                try:
                    committed, detail = action_rdf.write_action_version_invalidated(
                        rdf4j_client, decision_id, pinned_sha256, current_sha256, datetime.now(timezone.utc),
                        from_status="APPROVED" if row["status"] == "APPROVED" else "EXECUTING",
                    )
                finally:
                    rdf4j_client.close()
                if not committed:
                    raise ApplicationError(f"could not record action-version invalidation for {decision_id!r}: {detail[:300]}")
                with get_conn() as conn:
                    update_status(conn, decision_id, "ACTION_VERSION_INVALIDATED")
                raise ApplicationError(
                    f"decision {decision_id!r} pinned action {row['action_type']!r} sha256={pinned_sha256!r} "
                    f"but the current contract is sha256={current_sha256!r} (F34) — invalidated, never executed",
                    non_retryable=True,
                )

        from_status = "APPROVED" if row["status"] == "APPROVED" else "EXECUTING"
        action = get_action_type(row["action_type"], action_version_dir)
        parameters = row["parameters"]
        transfer_fields: dict[str, Any] = {}
        if row["action_type"] == "transfer_inventory":
            transfer_fields = {
                "quantity": parameters["quantity"],
                "source_warehouse": parameters["source_warehouse"],
                "destination_warehouse": parameters["destination_warehouse"],
            }
        rdf4j_client = self._rdf4j_client()
        try:
            committed, detail = action_rdf.write_execution_started(
                rdf4j_client, decision_id, action_execution_id,
                external_system=action.raw["external_operation"]["system"],
                external_operation=action.raw["external_operation"]["operation"],
                temporal_workflow_id=activity.info().workflow_id,
                started_at=datetime.now(timezone.utc),
                from_status=from_status,
                **transfer_fields,
            )
        finally:
            rdf4j_client.close()
        if not committed:
            raise ApplicationError(f"could not record execution start for {decision_id!r}: {detail[:300]}")
        with get_conn() as conn:
            update_status(conn, decision_id, "EXECUTING")

        return {
            "decision_id": decision_id,
            "action_type": row["action_type"],
            "action_version": row["action_version"],
            "parameters": row["parameters"],
            "actor_id": row["actor_id"],
        }

    @activity.defn(name="call_external_action")
    def call_external_action(self, action_execution_id: str, action_type: str, parameters: dict) -> dict[str, Any]:
        """spec 06: "call external API with action_execution_id as the
        idempotency key; persist command receipt/status" (the RDF
        persistence itself happens in observe_and_finalize, once the
        outcome is known — see services/common/action_rdf.py's module
        docstring for why exactly two writes, not three)."""
        if TEST_MODE:
            # F12 checkpoint: "worker crash pre-call" — BEFORE any external
            # HTTP call is even built. No-op unless a test armed this exact
            # action_execution_id (services/common/test_hooks.py).
            test_hooks.maybe_pause(get_conn, action_execution_id, "pre_call", heartbeat=activity.heartbeat)
        before: dict[str, Any] = {}

        if action_type == "transfer_inventory":
            with get_conn() as conn:
                src = get_current_inventory(conn, parameters["part"], parameters["source_warehouse"])
                dst = get_current_inventory(conn, parameters["part"], parameters["destination_warehouse"])
            before["source_available_before"] = src["available"] if src else 0
            before["destination_available_before"] = dst["available"] if dst else 0
            # WMS never learns canonical part ids (services/common/identity_lookup.py's
            # module docstring) — reverse-resolve parameters["part"] (always
            # canonical) to WMS's OWN local id before building the request.
            rdf4j_client = self._rdf4j_client()
            try:
                wms_local_part = resolve_canonical_part_to_source_local(rdf4j_client, parameters["part"], "WMS")
            finally:
                rdf4j_client.close()
            if wms_local_part is None:
                raise ApplicationError(
                    f"no WMS identity mapping found for canonical part {parameters['part']!r}", non_retryable=True,
                )
            with httpx.Client(base_url=self.config.wms_base_url, timeout=10.0) as wms:
                resp = wms.post(
                    "/transfers",
                    json={
                        "action_execution_id": action_execution_id,
                        "source": parameters["source_warehouse"],
                        "destination": parameters["destination_warehouse"],
                        "part": wms_local_part,
                        "quantity": parameters["quantity"],
                    },
                )
        elif action_type == "expedite_purchase_order":
            with httpx.Client(base_url=self.config.erp_base_url, timeout=10.0) as erp:
                resp = erp.post(
                    f"/purchase_orders/{parameters['po_id']}/expedite",
                    json={"action_execution_id": action_execution_id, "expedite_fee": parameters.get("expedite_fee", 0)},
                )
        elif action_type == "reschedule_work_order":
            with httpx.Client(base_url=self.config.mes_base_url, timeout=10.0) as mes:
                resp = mes.post(
                    f"/work_orders/{parameters['work_order_id']}/reschedule",
                    json={"action_execution_id": action_execution_id, "new_planned_start": parameters["new_planned_start"]},
                )
        else:
            raise ApplicationError(f"no external dispatcher for action_type {action_type!r}", non_retryable=True)

        try:
            body = resp.json()
        except ValueError:
            body = {"raw_text": resp.text[:2000]}
        return {"http_status": resp.status_code, "body": body, **before}

    @activity.defn(name="observe_and_finalize")
    def observe_and_finalize(
        self,
        decision_id: str,
        action_execution_id: str,
        action_type: str,
        parameters: dict,
        actor_id: str,
        command_result: dict,
    ) -> dict[str, Any]:
        """spec 06: "wait for correlated CDC observation; evaluate outcome
        predicate; set final status". The SECOND (and last) RDF write per
        ActionExecution — see services/common/action_rdf.py."""
        if TEST_MODE:
            # F13 checkpoint: "worker crash post-call/pre-record" — the WMS
            # call in call_external_action already COMPLETED (its Temporal
            # activity result is durably recorded), but nothing has been
            # observed/written yet. A crash here means Temporal replays only
            # THIS activity on restart — call_external_action is never
            # re-invoked, so no duplicate WMS effect is possible by
            # construction.
            test_hooks.maybe_pause(get_conn, action_execution_id, "post_call_pre_record", heartbeat=activity.heartbeat)
        # Phase 7 scope note: this activity only receives action_type/parameters
        # (not the decision's row), so it cannot look up action_version_dir
        # the way verify_and_start_execution above does. Deliberately left
        # at the "v1" default — the only field read off `action` below is
        # `compensation_mode`, which contracts/actions/v2/transfer_inventory.yaml
        # keeps IDENTICAL to v1 ("compensatable"), so this is a real but
        # currently harmless gap, not a silent one: a FUTURE action version
        # that changes compensation_mode would need this threaded through
        # the workflow signature the same way decision_id already is.
        action = get_action_type(action_type)
        observation_timeout_s = 30.0  # contracts/actions/v1/*.yaml observation.timeout: PT30S, all three

        if action_type == "transfer_inventory":
            transfer_record = None
            # A definitive local failure (F01-style: bad request) never got
            # a WMS row at all — F14/F21's "commit_then_timeout"/
            # 500-before-commit faults DO still create a real transfers row
            # via WMS's own idempotency table (services/wms/transfers.py),
            # so those still reach the CDC poll below rather than
            # short-circuiting here.
            if command_result["http_status"] not in (200, 409):
                verdict = outcome_eval.OutcomeVerdict(
                    outcome_eval.OUTCOME_UNKNOWN, {}, command_result,
                    f"unexpected WMS command HTTP status {command_result['http_status']}",
                )
            else:
                rdf4j_client = self._rdf4j_client()
                try:
                    transfer_record = _poll_wms_transfer_record(rdf4j_client, action_execution_id, observation_timeout_s)
                finally:
                    rdf4j_client.close()
                verdict = outcome_eval.evaluate_transfer_outcome(
                    parameters["quantity"],
                    command_result.get("source_available_before", 0),
                    command_result.get("destination_available_before", 0),
                    transfer_record,
                )
        else:
            verdict = outcome_eval.evaluate_command_response_outcome(action_type, command_result["http_status"], command_result["body"])

        compensation_status = "NOT_APPLICABLE"
        compensating_action_execution_id = None
        if verdict.status == outcome_eval.DIVERGED and action_type == "transfer_inventory" and action.compensation_mode == "compensatable":
            compensating_action_execution_id = f"{action_execution_id}-reverse"
            with httpx.Client(base_url=self.config.wms_base_url, timeout=10.0) as wms:
                rresp = wms.post(
                    f"/transfers/{action_execution_id}/reverse",
                    json={"action_execution_id": compensating_action_execution_id},
                )
            compensation_status = "COMPENSATED" if rresp.status_code == 200 else "COMPENSATION_FAILED"
        elif verdict.status == outcome_eval.DIVERGED:
            # Never invent compensation for an ActionType whose contract
            # doesn't declare compensation.mode: compensatable (spec 06:
            # "Compensation only where the action contract says
            # compensatable").
            compensation_status = "MANUAL_RECOVERY_REQUIRED"

        reconciliation_state = {
            outcome_eval.OBSERVED_SUCCESS: "CONVERGED",
            outcome_eval.DIVERGED: "COMPENSATED" if compensation_status == "COMPENSATED" else "DIVERGED",
            outcome_eval.OUTCOME_UNKNOWN: "AWAITING_OBSERVATION",
            outcome_eval.EXECUTION_FAILED: "FAILED",
        }[verdict.status]

        rdf4j_client = self._rdf4j_client()
        try:
            committed, detail = action_rdf.write_execution_finalized(
                rdf4j_client,
                decision_id=decision_id,
                action_execution_id=action_execution_id,
                executed_by_actor_id=actor_id,
                final_status=verdict.status,
                command_status=str(command_result.get("http_status")),
                command_receipt_json=action_rdf.json_for_rdf(command_result.get("body", {})),
                completed_at=datetime.now(timezone.utc),
                outcome_id=f"O-{action_execution_id}",
                reconciliation_state=reconciliation_state,
                expected_effect_json=action_rdf.json_for_rdf(verdict.expected_effect),
                observed_effect_json=action_rdf.json_for_rdf(verdict.observed_effect),
                observed_at=datetime.now(timezone.utc),
                compensation_status=compensation_status,
                source_evidence_lsn=None,
                compensating_action_execution_id=compensating_action_execution_id,
            )
        finally:
            rdf4j_client.close()
        if not committed:
            raise ApplicationError(f"could not record execution outcome for {decision_id!r}: {detail[:300]}")
        with get_conn() as conn:
            update_status(conn, decision_id, verdict.status)

        return {
            "decision_id": decision_id,
            "action_execution_id": action_execution_id,
            "status": verdict.status,
            "reason": verdict.reason,
            "compensation_status": compensation_status,
        }
