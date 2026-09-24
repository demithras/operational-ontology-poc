"""Starts (or idempotently reuses) the baseline's ActionExecutionWorkflow —
same role as services/decision_service/execution.py, targeting
services/baseline/config.BASELINE_ACTION_TASK_QUEUE instead."""

from __future__ import annotations

from temporalio.client import Client, WorkflowHandle
from temporalio.exceptions import WorkflowAlreadyStartedError

from services.action_worker.workflows import ActionExecutionWorkflow
from services.baseline.config import BASELINE_ACTION_TASK_QUEUE


def action_execution_id_for(decision_id: str) -> str:
    return f"AX-{decision_id}"


async def start_or_get_execution(temporal_client: Client, decision_id: str) -> tuple[WorkflowHandle, bool]:
    action_execution_id = action_execution_id_for(decision_id)
    try:
        handle = await temporal_client.start_workflow(
            ActionExecutionWorkflow.run, args=[decision_id, action_execution_id],
            id=action_execution_id, task_queue=BASELINE_ACTION_TASK_QUEUE,
        )
        return handle, True
    except WorkflowAlreadyStartedError:
        return temporal_client.get_workflow_handle(action_execution_id), False
