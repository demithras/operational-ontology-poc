"""F27 (docs/experiment/spec/09_failure_and_adversarial_matrix.md):
"projection corrupt -> test hook: tamper with a row -> the consistency
checker detects the mismatch".

The "test hook" IS the tampering itself: any direct SQL UPDATE against a
business column (the kind of thing this phase's honesty rule exists to
catch — an out-of-band write that bypasses services/projection_builder's
own write path) leaves `content_hash` referring to the row's PRE-tamper
business fields. `check_row`/`check_table` simply recompute the hash from
current business-field values and compare.
"""

from __future__ import annotations

from services.projection_builder.hashing import row_content_hash


def check_row(table: str, row: dict) -> bool:
    """True if row is internally consistent (stored content_hash still
    matches its own current business fields)."""
    return row.get("content_hash") == row_content_hash(table, row)


def check_table(table: str, rows: list[dict]) -> list[dict]:
    """Returns the subset of `rows` that FAILED the consistency check (empty
    list = table is consistent). Each returned row carries its own
    recomputed hash under `_recomputed_content_hash` for diagnostics."""
    mismatches = []
    for row in rows:
        if not check_row(table, row):
            mismatches.append({**row, "_recomputed_content_hash": row_content_hash(table, row)})
    return mismatches
