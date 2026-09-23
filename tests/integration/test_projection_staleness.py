"""Phase 4 item 4 / F26 (docs/experiment/spec/09_failure_and_adversarial_matrix.md
"hot projection stale -> freshness visible; policy may reject"): an
injected 30s-stale projection must be detectable.

Freshness is evaluated at READ time against the row's `as_of` (see
services/projection_builder/freshness.py's docstring for why it is not a
stored column) — this test proves that both directly (pure function,
no I/O) and end to end (a real row's `as_of` pushed back via SQL, then read
through services.projection_builder.reader, which is what any future
Decision API read path would call).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.projection_builder import freshness
from services.projection_builder.reader import get_work_order_risk
from tests.integration.conftest import wait_until


def test_freshness_evaluate_pure_function_boundary():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert freshness.evaluate(now, now=now, max_age_s=5) == freshness.FRESH
    assert freshness.evaluate(now - timedelta(seconds=5), now=now, max_age_s=5) == freshness.FRESH
    assert freshness.evaluate(now - timedelta(seconds=6), now=now, max_age_s=5) == freshness.STALE
    assert (
        freshness.evaluate(now - timedelta(seconds=30), now=now, max_age_s=5)
        == freshness.STALE
    )


def test_injected_30s_stale_projection_row_is_detected(ontology_hot_conn):
    row = wait_until(lambda: get_work_order_risk(ontology_hot_conn, "WO-42"), timeout_s=20.0)
    assert row is not None, "expected an existing work_order_risk row for WO-42 to inject staleness into"

    with ontology_hot_conn.cursor() as cur:
        cur.execute(
            "UPDATE work_order_risk SET as_of = now() - interval '30 seconds' WHERE work_order_id = %s",
            ("WO-42",),
        )
    try:
        tampered = get_work_order_risk(ontology_hot_conn, "WO-42")
        assert tampered is not None
        assert tampered["freshness_status"] == freshness.STALE, (
            "F26: a 30s-stale as_of must be reported STALE, never silently used as fresh"
        )
    finally:
        # Best-effort restore so this test doesn't leave a permanently
        # tampered row behind — the next live poll cycle overwrites it
        # regardless, this just avoids confusing an observer in between.
        with ontology_hot_conn.cursor() as cur:
            cur.execute("UPDATE work_order_risk SET as_of = now() WHERE work_order_id = %s", ("WO-42",))
