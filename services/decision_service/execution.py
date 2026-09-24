"""Starts (or idempotently reuses) the Temporal ActionExecutionWorkflow for
an APPROVED decision — docs/experiment/spec/06_decision_and_action_runtime.md
execute(): "verify immutable content hash [...] create ActionExecution(action_execution_id);
start Temporal workflow(action_execution_id)".

Imports services/action_worker/workflows.py for a TYPE-SAFE
`client.start_workflow(ActionExecutionWorkflow.run, ...)` call — safe here
(unlike from INSIDE a workflow) because services/decision_service is a
plain FastAPI process, never itself executed inside Temporal's workflow
sandbox.
"""

from __future__ import annotations

from temporalio.client import Client, WorkflowHandle
from temporalio.exceptions import WorkflowAlreadyStartedError

from services.action_worker.config import TASK_QUEUE
from services.action_worker.workflows import ActionExecutionWorkflow


def action_execution_id_for(decision_id: str) -> str:
    """One execution per decision (spec 06: 'ActionExecution.idempotencyKey
    unique per logical action') — deterministic from decision_id so a
    RETRIED execute() call for the SAME decision always resolves to the
    SAME Temporal workflow id, never a second one (F10/F25)."""
    return f"AX-{decision_id}"


async def start_or_get_execution(temporal_client: Client, decision_id: str) -> tuple[WorkflowHandle, bool]:
    """Returns (handle, started_now). started_now=False means an execution
    for this decision was ALREADY running/completed — the caller reused it
    rather than starting a duplicate (F10: 'duplicate API request -> same
    logical effect once')."""
    action_execution_id = action_execution_id_for(decision_id)
    try:
        handle = await temporal_client.start_workflow(
            ActionExecutionWorkflow.run,
            args=[decision_id, action_execution_id],
            id=action_execution_id,
            task_queue=TASK_QUEUE,
        )
        return handle, True
    except WorkflowAlreadyStartedError:
        return temporal_client.get_workflow_handle(action_execution_id), False
