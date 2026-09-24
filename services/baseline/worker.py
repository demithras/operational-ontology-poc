#!/usr/bin/env python3
"""services/baseline's Temporal worker entrypoint — same shape as
services/action_worker/worker.py, polling
services/baseline/config.BASELINE_ACTION_TASK_QUEUE and hosting the SAME
services/action_worker/workflows.ActionExecutionWorkflow class (fairness:
"SAME Temporal execution pattern", spec 10) with
services/baseline/activities.BaselineActionActivities's three activities.
"""

from __future__ import annotations

import asyncio
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from temporalio.client import Client  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from services.action_worker import health  # noqa: E402
from services.action_worker.workflows import ActionExecutionWorkflow  # noqa: E402
from services.baseline.activities import BaselineActionActivities  # noqa: E402
from services.baseline.config import BASELINE_ACTION_TASK_QUEUE, from_env  # noqa: E402
from services.common.db import open_pool  # noqa: E402


async def run() -> None:
    config = from_env()
    state = health.HealthState()
    health.start_health_server(state, int(os.environ.get("OO_BASELINE_ACTION_WORKER_HEALTH_PORT", "8094")))

    open_pool()
    activities = BaselineActionActivities(config)

    client = await Client.connect(config.temporal_address, namespace="default")
    with ThreadPoolExecutor(max_workers=20) as executor:
        worker = Worker(
            client, task_queue=BASELINE_ACTION_TASK_QUEUE, workflows=[ActionExecutionWorkflow],
            activities=[activities.verify_and_start_execution, activities.call_external_action, activities.observe_and_finalize],
            activity_executor=executor,
        )
        state.set_ready(True)
        print(f"[baseline_action_worker] polling task queue {BASELINE_ACTION_TASK_QUEUE!r} at {config.temporal_address}")
        await worker.run()


def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
