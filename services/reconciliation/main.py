#!/usr/bin/env python3
"""services/reconciliation poll loop entrypoint (docker-compose service
`reconciliation`) — same short-poll pattern as services/projection_builder/main.py.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from services.common.db import get_conn, open_pool  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.reconciliation import health  # noqa: E402
from services.reconciliation.config import from_env  # noqa: E402
from services.reconciliation.reconcile import reconcile_one, watched_decisions  # noqa: E402

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()


def apply_schema() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()


def run(client: RDF4JClient, poll_interval_s: float, state: health.HealthState) -> None:
    while True:
        t0 = time.monotonic()
        try:
            with get_conn() as conn:
                decisions = watched_decisions(conn)
                state.set("decisions_watched", len(decisions))
                for row in decisions:
                    outcome = reconcile_one(conn, client, row)
                    if outcome == "converged":
                        state.incr("convergences")
                    elif outcome == "diverged_alert_raised":
                        state.incr("alerts_raised")
            state.incr("cycles_completed")
            state.set_error(None)
            state.set_ready(True)
        except Exception as e:  # noqa: BLE001 - a failed cycle must never crash the loop
            state.set_error(str(e))
        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, poll_interval_s - elapsed))


def main() -> int:
    config = from_env()
    state = health.HealthState()
    health.start_health_server(state, int(os.environ.get("OO_RECONCILIATION_HEALTH_PORT", "8093")))

    open_pool()
    apply_schema()

    client = RDF4JClient(base_url=config.rdf4j_base_url, repository=config.rdf4j_repository)
    try:
        run(client, config.poll_interval_s, state)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
