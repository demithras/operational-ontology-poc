"""Cross-process test-mode pause hooks for F12/F13 (worker crash injection,
docs/experiment/spec/09_failure_and_adversarial_matrix.md).

Only meaningful when OO_TEST_MODE=1 (the test suite arms these; production
code never does). Backed by a tiny ontology_hot table
(`test_action_worker_hooks`) because the TEST process (which issues a real
`docker compose kill action_worker`) and the activity being paused run in
DIFFERENT processes/containers — there is no shared in-process memory to
coordinate through, unlike services/wms's own in-memory FaultRegistry
(services/common/faults.py), which only ever needs to coordinate within
WMS's single process.

Usage: a test arms a (action_execution_id, checkpoint) pair BEFORE calling
execute(); services/action_worker/activities.py calls maybe_pause() at the
top of the matching activity. If armed for THAT checkpoint, it marks
`reached_at` (so the test can detect the checkpoint was actually hit) then
sleeps up to `pause_seconds`, heartbeating periodically if a heartbeat
callback is given — giving the test a window to `docker compose kill
action_worker` mid-activity and prove Temporal's own durable-execution
replay resumes correctly on a restarted worker, without duplicating any
external effect.
"""

from __future__ import annotations

import time
from typing import Callable

import psycopg

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS test_action_worker_hooks (
    action_execution_id TEXT PRIMARY KEY,
    checkpoint           TEXT NOT NULL,
    pause_seconds         DOUBLE PRECISION NOT NULL DEFAULT 6.0,
    reached_at             TIMESTAMPTZ,
    armed_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def apply_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def arm(conn: psycopg.Connection, action_execution_id: str, checkpoint: str, pause_seconds: float = 6.0) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO test_action_worker_hooks (action_execution_id, checkpoint, pause_seconds, reached_at)
            VALUES (%s, %s, %s, NULL)
            ON CONFLICT (action_execution_id) DO UPDATE
                SET checkpoint = EXCLUDED.checkpoint, pause_seconds = EXCLUDED.pause_seconds,
                    reached_at = NULL, armed_at = now()
            """,
            (action_execution_id, checkpoint, pause_seconds),
        )
    conn.commit()


def disarm(conn: psycopg.Connection, action_execution_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM test_action_worker_hooks WHERE action_execution_id = %s", (action_execution_id,))
    conn.commit()


def reached(conn: psycopg.Connection, action_execution_id: str, checkpoint: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT reached_at IS NOT NULL FROM test_action_worker_hooks WHERE action_execution_id = %s AND checkpoint = %s",
            (action_execution_id, checkpoint),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def maybe_pause(
    conn_factory: Callable[[], "psycopg._ConnectionContextManager"],
    action_execution_id: str,
    checkpoint: str,
    heartbeat: Callable[[str], None] | None = None,
) -> None:
    """Called from inside a Temporal activity. `conn_factory` is
    services.common.db.get_conn (a contextmanager). No-op (near-zero
    overhead) unless THIS action_execution_id is armed for THIS exact
    checkpoint AND has not already been reached once — every other test's
    execute() path never even queries this table conditionally beyond the
    one cheap SELECT below.

    Consumed on first reach (`reached_at IS NULL` in the WHERE clause,
    never re-checked afterwards): a killed activity attempt is retried by
    Temporal as a brand-new invocation of the SAME activity function, which
    would otherwise hit this SAME pause again — and if `pause_seconds`
    exceeds the activity's own `start_to_close_timeout` (as it legitimately
    can, to give a real `docker kill` time to land), every retry would then
    time out at the SAME checkpoint forever, never reaching the real call.
    One pause per armed (action_execution_id, checkpoint) is exactly what a
    "kill it once, then let it recover" fault test needs — same
    consume-on-first-use semantics as services/common/faults.py's WMS
    FaultRegistry (`scope="action_execution_id"`)."""
    with conn_factory() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pause_seconds FROM test_action_worker_hooks "
                "WHERE action_execution_id = %s AND checkpoint = %s AND reached_at IS NULL",
                (action_execution_id, checkpoint),
            )
            row = cur.fetchone()
        if row is None:
            return
        pause_seconds = float(row[0])
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE test_action_worker_hooks SET reached_at = now() WHERE action_execution_id = %s",
                (action_execution_id,),
            )
        conn.commit()

    deadline = time.monotonic() + pause_seconds
    while time.monotonic() < deadline:
        if heartbeat is not None:
            heartbeat(f"test_hooks.maybe_pause: paused at checkpoint {checkpoint!r}")
        time.sleep(0.5)
