"""The Temporal workflow implementing spec 06's execute()/workflow
pseudocode. Deliberately does NOT import services/action_worker/activities.py
(which pulls in psycopg/httpx/rdflib — Temporal's workflow sandbox forbids
non-deterministic I/O modules in workflow code) — activities are referenced
by NAME STRING only, matching services/action_worker/worker.py's
registration (`ActionActivities(config)`'s methods, `@activity.defn(name=...)`).

One workflow per logical action (spec 06: "start Temporal workflow
(action_execution_id)") — services/decision_service/app.py's execute()
endpoint starts this workflow with `id=action_execution_id`, so Temporal's
own workflow-id uniqueness is the FIRST idempotency layer (a duplicate
execute() call for the same decision reuses/observes the SAME workflow
rather than starting a second one — F10/F25).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

VERIFY_AND_START = "verify_and_start_execution"
CALL_EXTERNAL = "call_external_action"
OBSERVE_AND_FINALIZE = "observe_and_finalize"


@workflow.defn
class ActionExecutionWorkflow:
    @workflow.run
    async def run(self, decision_id: str, action_execution_id: str) -> dict[str, Any]:
        started = await workflow.execute_activity(
            VERIFY_AND_START,
            args=[decision_id, action_execution_id],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        command_result = await workflow.execute_activity(
            CALL_EXTERNAL,
            args=[action_execution_id, started["action_type"], started["parameters"]],
            # Generous but bounded: the external systems are local FastAPI
            # services (sub-second normally); F14's commit_then_timeout
            # fault deliberately sleeps up to ~6s server-side, so this must
            # comfortably exceed that rather than time out ON the fault
            # itself (which would just retry the SAME idempotent call).
            start_to_close_timeout=timedelta(seconds=20),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )

        result = await workflow.execute_activity(
            OBSERVE_AND_FINALIZE,
            args=[
                decision_id, action_execution_id, started["action_type"], started["parameters"],
                started["actor_id"], command_result,
            ],
            # Contract's observation.timeout (PT30S) plus margin for the
            # activity's own RDF read/write round trips; heartbeat_timeout
            # lets Temporal detect a genuinely wedged worker mid-poll
            # without waiting the full start_to_close_timeout.
            start_to_close_timeout=timedelta(seconds=45),
            heartbeat_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        return result
