"""Turns a projection row's contributing entities (services.projection_builder.
compute.EntityRef) into the "source event positions (per-source LSN/offset)"
docs/experiment/briefs/phase4.md item 1 requires on every row, by looking
each one up in the oo:SourcePosition index
(services/projection_builder/rdf_reader.py::fetch_source_positions).

CLASS_TO_SOURCE mirrors services/ingestion/mapping.py's TABLE_SPECS
(fac: class name -> owning (system, table)) for exactly the classes this
phase's projections touch. fac:Part is deliberately omitted: InventoryLot/
BomRequirement/PurchaseOrderLine reference Part by its RESOLVED CANONICAL
id, but oo:SourcePosition for erp.parts is keyed by ERP's own LOCAL id
(pre-resolution) — the two id spaces don't match, and Part identity is not
load-bearing for shortage/inventory math, so it is simply left out of a
row's source_positions rather than looked up incorrectly.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.projection_builder.compute import EntityRef

CLASS_TO_SOURCE: dict[str, tuple[str, str]] = {
    "WorkOrder": ("mes", "work_orders"),
    "BomRequirement": ("mes", "bom_requirements"),
    "InventoryLot": ("wms", "inventory_lots"),
    "PurchaseOrder": ("erp", "purchase_orders"),
    "PurchaseOrderLine": ("erp", "purchase_order_lines"),
    "Warehouse": ("wms", "warehouses"),
}

PositionIndex = dict[tuple[str, str, str], dict[str, str | None]]


def build_source_positions(entities: tuple[EntityRef, ...], position_index: PositionIndex) -> list[dict]:
    """Deduplicated, sorted list of {system, table, pk, lsn, version} for
    every contributing entity that has a recorded oo:SourcePosition. An
    entity with no recorded position (e.g. observed via the initial
    snapshot before any oo:SourcePosition write, which should not happen in
    steady state but is handled rather than crashing a build cycle) is
    simply omitted."""
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for ref in entities:
        source = CLASS_TO_SOURCE.get(ref.class_name)
        if source is None:
            continue
        system, table = source
        key = (system, table, ref.local_id)
        if key in seen:
            continue
        seen.add(key)
        pos = position_index.get(key)
        if pos is None:
            continue
        out.append(
            {
                "system": system,
                "table": table,
                "pk": ref.local_id,
                "lsn": pos.get("lsn"),
                "version": pos.get("version"),
                "observed_at": pos.get("observed_at"),
            }
        )
    out.sort(key=lambda r: (r["system"], r["table"], r["pk"]))
    return out


def latest_observed_at(source_positions: list[dict], fallback: datetime | None = None) -> datetime:
    """as_of for a row = the latest oo:lastObservedAt among its contributing
    source positions (docs/experiment/spec/04_architecture.md's consistency
    model: as_of reflects how fresh the OBSERVED data feeding this row is,
    not when the projection happened to be computed). Falls back to `now`
    if a row has no positioned contributors at all (e.g. an empty
    current_inventory build against a graph with no InventoryLot facts
    yet) — never raises, never fabricates a position that wasn't observed."""
    timestamps = [p["observed_at"] for p in source_positions if p.get("observed_at")]
    if not timestamps:
        return fallback or datetime.now(timezone.utc)
    return max(_parse_dt(t) for t in timestamps)


def _parse_dt(value: str) -> datetime:
    # oo:lastObservedAt is written as datetime.now(timezone.utc).isoformat()
    # by services/ingestion/store.py — always has an explicit offset.
    return datetime.fromisoformat(value)
