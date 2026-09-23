"""Ground-truth cross-system identity mapping for the seed dataset
(docs/experiment/spec/02_scope_and_non_goals.md "Semantic identity
alignment"), plus the one deliberately-discovered ID collision between the
bulk generator and the canonical incident fixture.

The generator (seed/generators/generate.py) mints ERP-local part ids as
PART-{i:05d} for i in range(500), i.e. PART-00000..PART-00499. The
canonical incident fixture (seed/fixtures/canonical_incident.yaml) assigns
its own part PX-17 the ERP-local id PART-00192 — which collides with
generated part index 192 (canonical id PX-0192, a *different* real-world
part). No other system's local ids collide (MES uses COMP-{i:05d} vs the
fixture's COMP-A17; WMS uses SKU-{100000+i} vs the fixture's SKU-88429).

Policy: the canonical fixture's ids are authoritative. When a generated
part's local id for one system collides with a fixture id, that ONE
system's row is dropped for that generated part (the part is simply absent
from that system's DB — the other 499/500 parts are unaffected, and the
part is still present in the other two systems). This is recorded
explicitly in identity_truth.json rather than silently overwritten.
"""

from __future__ import annotations

from typing import Any

SYSTEMS = ("ERP", "MES", "WMS")


def compute_identity(dataset_parts: list[dict[str, Any]], canonical_part: dict[str, Any]) -> dict[str, Any]:
    """Returns {"records": [...], "dropped": {"ERP": {canonical_part_id,...}, ...}}."""
    reserved = {sys: canonical_part["source_identity_map"][sys] for sys in SYSTEMS}
    dropped: dict[str, set[str]] = {sys: set() for sys in SYSTEMS}
    records: list[dict[str, Any]] = []

    for part in dataset_parts:
        record: dict[str, Any] = {"canonical_part_id": part["canonical_part_id"]}
        notes = []
        for sys in SYSTEMS:
            local_id = part["source_identity_map"][sys]
            if local_id == reserved[sys]:
                dropped[sys].add(part["canonical_part_id"])
                record[sys] = None
                notes.append(
                    f"{sys} id {local_id} collides with canonical incident part "
                    f"{canonical_part['canonical_id']}; dropped from {sys} for this part"
                )
            else:
                record[sys] = local_id
        if notes:
            record["note"] = "; ".join(notes)
        records.append(record)

    records.append(
        {
            "canonical_part_id": canonical_part["canonical_id"],
            "ERP": reserved["ERP"],
            "MES": reserved["MES"],
            "WMS": reserved["WMS"],
            "note": "canonical incident fixture part (seed/fixtures/canonical_incident.yaml)",
        }
    )

    return {"records": records, "dropped": {sys: sorted(ids) for sys, ids in dropped.items()}}
