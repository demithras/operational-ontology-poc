#!/usr/bin/env python3
"""Projection-builder poll loop entrypoint (docker-compose service
`projection_builder`, command override on the shared root Dockerfile — same
one-Dockerfile-many-commands pattern as erp/mes/wms/ingestion).

"Triggered by ingestion updates or a short poll" (docs/experiment/briefs/
phase4.md item 1) — this repo picks the short-poll option: simpler than
wiring a second Kafka consumer group off the ingestion topics just to learn
"something changed" (ingestion's own health counters already expose that,
services/projection_builder could poll THEM instead of RDF4J directly, but
that's an unnecessary indirection when a fixed-cadence full rebuild is
already provably correct and fast enough at this dataset's scale — see
docs/experiment/implementation-notes.md Phase 4 section for the measured
build duration).
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
from services.projection_builder import health  # noqa: E402
from services.projection_builder.builder import build_all  # noqa: E402

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
                build_all(client, conn)
            state.incr("builds_completed")
            state.set_error(None)
            state.set_ready(True)
        except Exception as e:  # noqa: BLE001 - a failed build cycle must never crash the loop
            state.incr("builds_failed")
            state.set_error(str(e))
        state.set_last_build_ms((time.monotonic() - t0) * 1000.0)
        elapsed = time.monotonic() - t0
        time.sleep(max(0.0, poll_interval_s - elapsed))


def main() -> int:
    rdf4j_base = os.environ.get("RDF4J_BASE_URL", "http://localhost:15480/rdf4j-server")
    rdf4j_repo = os.environ.get("RDF4J_REPOSITORY", "oo")
    poll_interval_s = float(os.environ.get("OO_PROJECTION_POLL_INTERVAL_S", "3"))
    health_port = int(os.environ.get("OO_PROJECTION_HEALTH_PORT", "8091"))

    state = health.HealthState()
    health.start_health_server(state, health_port)

    open_pool()
    apply_schema()

    client = RDF4JClient(base_url=rdf4j_base, repository=rdf4j_repo)
    try:
        run(client, poll_interval_s, state)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
