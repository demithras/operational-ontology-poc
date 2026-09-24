#!/usr/bin/env python3
"""services/action_worker entrypoint (docker-compose service `action_worker`,
command override on the shared root Dockerfile — same one-Dockerfile-many-
commands pattern as erp/mes/wms/ingestion/projection_builder/decision_service).

Starts the health HTTP server (services/action_worker/health.py) THEN
connects to Temporal and runs a Worker polling
services/action_worker/config.py::TASK_QUEUE, hosting
services/action_worker/workflows.py::ActionExecutionWorkflow and
services/action_worker/activities.py::ActionActivities's three activities.
Sync activities (this repo's established style) run under a
ThreadPoolExecutor, per temporalio's own requirement for non-async
activity functions.
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
from services.action_worker.activities import ActionActivities  # noqa: E402
from services.action_worker.config import TASK_QUEUE, from_env  # noqa: E402
from services.action_worker.workflows import ActionExecutionWorkflow  # noqa: E402
from services.common import test_hooks  # noqa: E402
from services.common.db import get_conn, open_pool  # noqa: E402


async def run() -> None:
    config = from_env()
    state = health.HealthState()
    health.start_health_server(state, int(os.environ.get("OO_ACTION_WORKER_HEALTH_PORT", "8092")))

    open_pool()
    if os.environ.get("OO_TEST_MODE") == "1":
        # F12/F13 test-mode pause hooks (services/common/test_hooks.py) —
        # only needed when the fault-injection test suite might arm one;
        # applying it unconditionally in production would be harmless too,
        # but this keeps prod startup free of test-only schema.
        with get_conn() as conn:
            test_hooks.apply_schema(conn)
    activities = ActionActivities(config)

    client = await Client.connect(config.temporal_address, namespace="default")
    with ThreadPoolExecutor(max_workers=20) as executor:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[ActionExecutionWorkflow],
            activities=[
                activities.verify_and_start_execution,
                activities.call_external_action,
                activities.observe_and_finalize,
            ],
            activity_executor=executor,
        )
        state.set_ready(True)
        print(f"[action_worker] polling task queue {TASK_QUEUE!r} at {config.temporal_address}")
        await worker.run()


def main() -> int:
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
