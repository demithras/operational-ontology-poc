"""Phase 4 item 4 / F27 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"projection corrupt -> test hook: tamper with a row -> the consistency
checker detects the mismatch").

The "test hook" is the direct SQL UPDATE below, standing in for any
out-of-band write that bypasses services/projection_builder's own write
path (writer.py, which always recomputes content_hash together with the
business fields it hashes). services/projection_builder/consistency.py is
the checker under test.
"""

from __future__ import annotations

from psycopg.rows import dict_row

from services.projection_builder import consistency
from services.projection_builder.reader import get_work_order_risk
from tests.integration.conftest import wait_until


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

    # Corrupt a business field directly, WITHOUT going through
    # services/projection_builder/writer.py (which would recompute
    # content_hash together with it) — this is exactly the "tamper with a
    # row" test hook F27 asks for.
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
        # The next live poll cycle overwrites this row anyway (full
        # rebuild-from-RDF every cycle), but repair it immediately so a
        # concurrently-running test doesn't observe the corrupted value.
        with ontology_hot_conn.cursor() as cur:
            cur.execute(
                "UPDATE work_order_risk SET shortage = shortage - 9999 WHERE work_order_id = %s", ("WO-42",)
            )
