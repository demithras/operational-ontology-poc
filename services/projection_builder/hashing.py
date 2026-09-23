"""Single source of truth for which columns of each hot-projection table are
"deterministic business fields" vs "timestamp/technical" (docs/experiment/spec/07_versioning_and_replay.md
"Projection rebuild": `hash(rebuilt_projection) == hash(expected_projection)
for stable deterministic fields, with documented exclusions for
timestamps/technical IDs").

Excluded from every table's BUSINESS_COLUMNS, and therefore from both
row_content_hash and table_hash: `computed_at` (wall-clock build time),
`as_of` (latest observed source timestamp — genuinely a timestamp, not
business data), `source_positions` (embeds `observed_at` timestamps),
`content_hash` (would be self-referential), and the three
`projection_definition_*`/`ontology_contract_version` columns (contract
identifiers, not projected business facts — they only change when the
contract itself changes, not when the same contract recomputes the same
world state).
"""

from __future__ import annotations

import hashlib
import json

BUSINESS_COLUMNS: dict[str, tuple[str, ...]] = {
    "work_order_risk": ("work_order_id", "warehouse", "shortage", "at_risk", "severity"),
    "transfer_candidates": (
        "candidate_id",
        "work_order_id",
        "part",
        "destination_warehouse",
        "source_warehouse",
        "candidate_quantity",
        "available_at_source",
    ),
    "current_inventory": ("part", "warehouse", "on_hand", "reserved", "available", "quality_status"),
    "action_eligibility_summary": (
        "work_order_id",
        "at_risk",
        "shortage",
        "severity",
        "transfer_candidate_count",
        "max_single_candidate_quantity",
        "total_candidate_quantity",
        "mitigation_feasible",
    ),
}


def _canonical_json(fields: dict) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)


def row_content_hash(table: str, row: dict) -> str:
    cols = BUSINESS_COLUMNS[table]
    payload = _canonical_json({c: row[c] for c in cols})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def table_hash(table: str, rows: list[dict]) -> str:
    """Order-independent combined hash over every row's business fields —
    used by services/projection_builder/rebuild.py's before/after
    comparison. Sorting the per-row canonical strings makes this
    independent of row insertion/SELECT order."""
    cols = BUSINESS_COLUMNS[table]
    canonical_rows = sorted(_canonical_json({c: row[c] for c in cols}) for row in rows)
    return hashlib.sha256("\n".join(canonical_rows).encode("utf-8")).hexdigest()
