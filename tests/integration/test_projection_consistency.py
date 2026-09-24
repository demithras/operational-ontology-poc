"""Phase 4 item 4 / F27 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"projection corrupt -> test hook: tamper with a row -> the consistency
checker detects the mismatch").

The "test hook" is the direct SQL UPDATE below, standing in for any
out-of-band write that bypasses services/projection_builder's own write
path (writer.py, which always recomputes content_hash together with the
business fields it hashes). services/projection_builder/consistency.py is
the checker under test.

Phase 10b orchestrator correction: `test_tampered_row_fails_consistency_
check` is a genuine TEST RACE, not a real F27 defect — confirmed by the
orchestrator re-running it alone 3/3 green. Since Phase 10a,
`services/projection_builder/builder.py`'s `build_all()` does a FULL
rebuild-from-RDF of `work_order_risk` on every ~3s poll cycle; if that
cycle lands between this test's tamper UPDATE and its consistency-check
SELECT, the row is silently "healed" back to its correct value before the
assertion ever runs, and `check_row()` correctly (but misleadingly, for
THIS test's purpose) returns True.

Fixed by acquiring the SAME `pg_advisory_lock(hashtextextended(
'oo_poc_projection_rebuild', 0))` key `build_all()` itself takes as the
FIRST statement of its own transaction (services/projection_builder/
builder.py) — a session-scoped (not transaction-scoped) advisory lock held
across the whole tamper -> check -> restore window, so any concurrent
`build_all()` call (the live poll loop, or a manual `make
rebuild-projections`) blocks until this test releases it. This is mutual
exclusion via the exact primitive the builder already uses for
writer-vs-writer serialization (Phase 10a step 0a) — applied here for
tamper-vs-writer serialization instead.
"""

from __future__ import annotations

from contextlib import contextmanager

from psycopg.rows import dict_row

from services.projection_builder import consistency
from services.projection_builder.reader import get_work_order_risk
from tests.integration.conftest import wait_until

_BUILDER_LOCK_SQL = "SELECT pg_advisory_lock(hashtextextended('oo_poc_projection_rebuild', 0))"
_BUILDER_UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtextextended('oo_poc_projection_rebuild', 0))"


@contextmanager
def _builder_paused(conn):
    """Blocks services/projection_builder's own build_all() (live poll loop
    or a manual rebuild) from running for the duration of this context —
    same advisory-lock key build_all() itself takes first, so any
    concurrent caller simply waits its turn instead of racing us."""
    with conn.cursor() as cur:
        cur.execute(_BUILDER_LOCK_SQL)
    try:
        yield
    finally:
        with conn.cursor() as cur:
            cur.execute(_BUILDER_UNLOCK_SQL)


def _fetch_row(conn, work_order_id: str) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM work_order_risk WHERE work_order_id = %s", (work_order_id,))
        return cur.fetchone()


def test_untampered_row_passes_consistency_check(ontology_hot_conn):
    wait_until(lambda: get_work_order_risk(ontology_hot_conn, "WO-42"), timeout_s=20.0)
    row = _fetch_row(ontology_hot_conn, "WO-42")
    assert row is not None
    assert consistency.check_row("work_order_risk", row) is True


def test_tampered_row_fails_consistency_check(ontology_hot_conn):
    wait_until(lambda: get_work_order_risk(ontology_hot_conn, "WO-42"), timeout_s=20.0)

    with _builder_paused(ontology_hot_conn):
        # Corrupt a business field directly, WITHOUT going through
        # services/projection_builder/writer.py (which would recompute
        # content_hash together with it) — this is exactly the "tamper
        # with a row" test hook F27 asks for. The builder cannot heal this
        # out from under us: it is blocked on the same advisory lock this
        # whole block holds.
        with ontology_hot_conn.cursor() as cur:
            cur.execute("UPDATE work_order_risk SET shortage = shortage + 9999 WHERE work_order_id = %s", ("WO-42",))

        try:
            row = _fetch_row(ontology_hot_conn, "WO-42")
            assert row is not None
            assert consistency.check_row("work_order_risk", row) is False, (
                "F27: a tampered row's content_hash must no longer match its (now different) business fields"
            )

            mismatches = consistency.check_table("work_order_risk", [row])
            assert len(mismatches) == 1
            assert mismatches[0]["_recomputed_content_hash"] != row["content_hash"]
        finally:
            # Repair before releasing the lock — the next live poll cycle
            # would overwrite this row anyway, but repairing inside the
            # held lock means no other concurrent reader ever observes the
            # corrupted value at all, not even transiently.
            with ontology_hot_conn.cursor() as cur:
                cur.execute(
                    "UPDATE work_order_risk SET shortage = shortage - 9999 WHERE work_order_id = %s", ("WO-42",)
                )


def test_tampered_row_fails_consistency_check_20x_under_load(ontology_hot_conn):
    """Orchestrator-required proof (Phase 10b): the fix above must hold up
    under load, not just once. Runs the full tamper -> check -> restore
    cycle 20 times in a row while services/projection_builder's live poll
    loop is genuinely active (it always is — part of the running stack,
    not started/stopped by this test), asserting every single iteration
    deterministically detects the tamper. Before the advisory-lock fix,
    this reproduced the race directly: some iterations passed, some
    silently found an already-healed row."""
    wait_until(lambda: get_work_order_risk(ontology_hot_conn, "WO-42"), timeout_s=20.0)

    failures_detected = 0
    for i in range(20):
        with _builder_paused(ontology_hot_conn):
            with ontology_hot_conn.cursor() as cur:
                cur.execute(
                    "UPDATE work_order_risk SET shortage = shortage + %s WHERE work_order_id = %s",
                    (1000 + i, "WO-42"),
                )
            try:
                row = _fetch_row(ontology_hot_conn, "WO-42")
                assert row is not None, f"iteration {i}: row disappeared"
                result = consistency.check_row("work_order_risk", row)
                assert result is False, f"iteration {i}: consistency check should have detected the tamper, got {result}"
                failures_detected += 1
            finally:
                with ontology_hot_conn.cursor() as cur:
                    cur.execute(
                        "UPDATE work_order_risk SET shortage = shortage - %s WHERE work_order_id = %s",
                        (1000 + i, "WO-42"),
                    )

    assert failures_detected == 20, f"expected the tamper to be detected on all 20 iterations, got {failures_detected}"
