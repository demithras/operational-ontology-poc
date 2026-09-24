"""Waits for the Temporal frontend + "default" namespace to be genuinely
usable — same "prove real API readiness from outside, don't trust a bare
TCP/docker healthcheck" pattern as services/decision_service/bootstrap_openfga.py
(OpenFGA) and services/ingestion/readiness.py (the whole CDC pipeline).

docker-compose.yml's `temporal` service healthcheck is a raw `nc -z`
TCP-listen check (the auto-setup image has no curl; same "no shell/curl
inside the container" situation as openfga/opa — see that section of
docs/experiment/implementation-notes.md). A listening gRPC port does NOT
yet mean the "default" namespace (auto-created by auto-setup.sh unless
SKIP_DEFAULT_NAMESPACE_CREATION is set) has finished being registered —
this module makes a REAL namespace-scoped RPC (`list_workflows`, which
returns cleanly with zero results on an empty namespace) and only succeeds
once that RPC itself succeeds.

Run as `make up`'s own bootstrap step (idempotent — connecting and listing
an empty namespace has no side effects) before services/action_worker
itself starts, mirroring bootstrap_openfga.py's placement in the Makefile.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from temporalio.client import Client

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _wait_ready(target_host: str, namespace: str, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client = await Client.connect(target_host, namespace=namespace)
            async for _ in client.list_workflows():
                break
            print(f"[bootstrap_temporal] namespace {namespace!r} ready at {target_host}")
            return
        except Exception as exc:  # noqa: BLE001 - retry on ANY connect/RPC failure
            last_error = exc
            await asyncio.sleep(1.0)
    raise TimeoutError(f"Temporal namespace {namespace!r} not ready after {timeout_s}s at {target_host}: {last_error}")


def main() -> int:
    # Same "container env var if present, else host-side db_env fallback"
    # pattern as services/decision_service/bootstrap_openfga.py::main — this
    # script runs on the HOST (via `make up`'s `.venv/bin/python`), where
    # TEMPORAL_ADDRESS (docker-compose.yml: "temporal:7233") is not a
    # resolvable hostname at all.
    target_host = os.environ.get("TEMPORAL_ADDRESS")
    if not target_host:
        sys.path.insert(0, str(REPO_ROOT))
        from seed import db_env

        db_env.load_dotenv()
        target_host = db_env.temporal_frontend_address()

    try:
        asyncio.run(_wait_ready(target_host, "default", timeout_s=60.0))
    except TimeoutError as exc:
        print(f"[bootstrap_temporal] FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
