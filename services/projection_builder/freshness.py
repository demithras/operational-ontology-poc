"""Projection freshness (docs/experiment/spec/04_architecture.md consistency
model: FRESH/STALE; F26 in docs/experiment/spec/09_failure_and_adversarial_matrix.md
"hot projection stale -> freshness visible; policy may reject").

Freshness is a RELATIONSHIP between a row's `as_of` and the current wall
clock, not a fact about the row alone — a row stamped FRESH at build time
is stale five minutes later even though nothing about the row itself
changed. So it is deliberately never stored as a column (see schema.sql's
header comment): every reader calls `evaluate()` against `now()` at read
time. This is also what makes F26 testable without waiting 30 real
seconds — a test can set a row's `as_of` back by interval '30 seconds' via
direct SQL and `evaluate()` will correctly report STALE immediately.
"""

from __future__ import annotations

from datetime import datetime, timezone

FRESH = "FRESH"
STALE = "STALE"

# docs/experiment/spec/09_failure_and_adversarial_matrix.md's staleness test
# threshold ("policy can require inventory freshness <= 5s") — matches
# experiments/exp-000/manifest.yaml policy.max_evidence_freshness_s and
# reference_model.state.PolicyConfig's default, kept as this module's own
# default rather than importing reference_model (projection_builder reads
# RDF, not the reference model) — callers needing a different threshold
# pass max_age_s explicitly.
DEFAULT_MAX_AGE_S = 5


def evaluate(as_of: datetime, now: datetime | None = None, max_age_s: int = DEFAULT_MAX_AGE_S) -> str:
    now = now or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    age_s = (now - as_of).total_seconds()
    return FRESH if age_s <= max_age_s else STALE
