"""`make wait-healthy` implementation.

Phase 2-4 services all declare a docker HEALTHCHECK, so the original
Makefile recipe's `docker compose ps --format '{{.Name}} {{.Health}}'` grep
worked. Phase 5's `openfga` and `opa` images have NEITHER a shell NOR
curl/wget (verified empirically: `docker run --entrypoint /bin/sh ...` ->
"no such file or directory"), so a CMD/CMD-SHELL healthcheck literally
cannot run inside those containers — there is nothing to grep for. Rather
than fake one, those two services declare no `healthcheck:` at all, and
this script treats "no healthcheck configured" (`Health == ""` in `docker
compose ps --format json`) as ready once the container's own `State` is
"running" — a real health signal for openfga/opa still exists, just from
OUTSIDE the container: services/decision_service/bootstrap_openfga.py polls
OpenFGA's real `/healthz` HTTP endpoint before writing anything, and OPA's
own `/health` endpoint responds within its (sub-second, verified
empirically) startup time.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time


def _ps_rows() -> list[dict]:
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        capture_output=True, text=True, check=True,
    )
    rows = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _not_ready(rows: list[dict]) -> list[str]:
    not_ready = []
    for row in rows:
        state = row.get("State", "")
        health = row.get("Health", "")
        ready = state == "running" and health in ("", "healthy")
        if not ready:
            not_ready.append(f"{row.get('Name', '?')} state={state} health={health or '(none)'}")
    return not_ready


def wait_healthy(timeout_s: float = 120.0, poll_interval_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_not_ready: list[str] = []
    while time.monotonic() < deadline:
        rows = _ps_rows()
        last_not_ready = _not_ready(rows)
        if not last_not_ready:
            print("all services healthy")
            return
        time.sleep(poll_interval_s)
    print("timed out waiting for healthy services:", file=sys.stderr)
    for line in last_not_ready:
        print(f"  {line}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    wait_healthy()
