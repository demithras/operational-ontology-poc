"""Shared setup helpers for tests/integration/test_decision_service_*.py.

Every test uses a SYNTHETIC part at the REAL WH-A/WH-B warehouses (already-
observed `fac:Warehouse` instances from the seeded stack — see
services/decision_service/evidence.py's `destination_exists` check) rather
than the canonical PX-17/WO-42 fixture, per the established convention
(docs/experiment/implementation-notes.md Phase 4 fix: "any FUTURE test that
mutates state via a `_test/*` endpoint should target a synthetic,
non-canonical entity"). This also sidesteps a genuine finding from Phase 5
implementation: `tests/integration/test_canonical_scenario.py` already
performs the canonical incident's OWN mitigation via a direct WMS call
(bypassing governance entirely, by design — it is a Phase 2 test), which
permanently leaves WO-42 in a MITIGATED (not at-risk) state for the rest of
any stack's lifetime. Governed-decision tests need their own, never-mutated
subjects.

SKU vs. canonical id (found empirically during implementation): a synthetic
part id used directly (e.g. "PX-TEST-01") gets QUARANTINED by the identity
resolver — `contracts/identity/v1/mapping_rules.yaml`'s WMS pattern rule
only recognizes `^SKU-(\\d{6})$` — so it never reaches RDF4J/the hot
projection at all (`services/ingestion/health.py`'s
`messages_quarantined_identity` counter is the tell). Every helper here
therefore takes a WMS-local SKU (`SKU-9NNNNN`, a range never used by
`seed/generators/generate.py`'s 100000-100499 or the canonical fixture's
88429) for the WMS-facing call, and returns/expects the CANONICAL id
(`sku_to_canonical`) for anything touching the hot projection or a propose()
request's `parameters.part` (which is canonical-id-typed, per
contracts/actions/v1/transfer_inventory.yaml).

Phase 5 fix (watermark-based evidence freshness — see
services/decision_service/evidence.py's module docstring and
docs/experiment/implementation-notes.md's Phase 5 fix section): freshness no
longer depends on how recently a row's OWN data changed, so
`set_inventory_and_wait` no longer needs to (and must not) manually bump
`as_of` to defeat a staleness check — a row set up minutes ago is exactly as
FRESH as one set up a millisecond ago, as long as the ingestion pipeline is
alive. The `propose_with_freshness_retry` crutch this file used to export is
gone entirely; every call site now calls propose() directly.
"""

from __future__ import annotations

import re

import httpx
import psycopg

from services.projection_builder import reader
from tests.integration.conftest import wait_until

_SKU_PATTERN = re.compile(r"^SKU-(\d{6})$")
_SKU_OFFSET = 100000


def sku_to_canonical(sku: str) -> str:
    match = _SKU_PATTERN.match(sku)
    if match is None:
        raise ValueError(f"{sku!r} does not match WMS's SKU-###### pattern (contracts/identity/v1/mapping_rules.yaml)")
    index = int(match.group(1)) - _SKU_OFFSET
    return f"PX-{index:04d}"


def set_inventory_and_wait(
    wms_client: httpx.Client,
    conn: psycopg.Connection,
    sku: str,
    warehouse_id: str,
    on_hand: int,
    reserved: int = 0,
    quality_status: str = "OK",
    timeout_s: float = 20.0,
) -> str:
    """Sets exact inventory via WMS's test-mode endpoint (WMS-local `sku`),
    and waits for the change to converge into the `current_inventory` hot
    projection under its resolved CANONICAL id (real CDC + identity
    resolution + projection-builder round trip — no shortcuts on VALUE
    correctness). Callers may call propose() any time after this returns —
    seconds, minutes, whatever — freshness is governed by the pipeline
    watermark (services/ingestion), not by when this specific row last
    changed. Returns the canonical part id to use in the propose() request."""
    canonical = sku_to_canonical(sku)
    resp = wms_client.post(
        "/_test/inventory/set",
        json={"part": sku, "warehouse_id": warehouse_id, "on_hand": on_hand, "reserved": reserved, "quality_status": quality_status},
    )
    assert resp.status_code == 200, f"_test/inventory/set failed: {resp.status_code} {resp.text}"

    # Poll for the row to show THIS call's exact value, not merely "a row
    # exists" — a bare existence check is a false-positive the moment a
    # test REUSES a (sku, warehouse) pair a previous run already converged
    # (found empirically: wait_until returned the OLD on_hand immediately,
    # before the new CDC update had propagated, because "exists" was already
    # true from the prior value).
    def _matches() -> dict | None:
        row = reader.get_current_inventory(conn, canonical, warehouse_id)
        if row is not None and row["on_hand"] == on_hand and row["quality_status"] == quality_status:
            return row
        return None

    row = wait_until(_matches, timeout_s=timeout_s)
    assert row is not None, (
        f"current_inventory row for canonical part={canonical} (sku={sku}) warehouse={warehouse_id} "
        f"never converged to on_hand={on_hand} quality_status={quality_status!r}"
    )
    return canonical


def ingestion_watermarks(ingestion_client: httpx.Client) -> dict[str, str]:
    """Reads services/ingestion's per-source watermark directly — used by
    tests that need to ASSERT freshness came from the watermark mechanism
    (not just observe the gate's aggregate verdict)."""
    r = ingestion_client.get("/health")
    r.raise_for_status()
    return r.json().get("watermarks", {})


def inventory_unchanged(wms_client: httpx.Client, sku: str, warehouse_id: str, expected_on_hand: int) -> bool:
    """H2/F01-F09 zero-external-effects proof, read through the REAL WMS API
    (never a direct DB peek), keyed by WMS's OWN local id (`sku`) — this
    observes exactly what an external auditor of WMS itself could see.
    services/wms/app.py has no GET /transfers LIST endpoint (only
    /transfers/{id}), so for a synthetic-entity test the more precise and
    equally valid proof is: the exact (sku, warehouse) pair this test
    controls has NOT moved. Any transfer touching it would change on_hand."""
    rows = wms_client.get("/inventory_lots", params={"part": sku, "warehouse_id": warehouse_id}).json()
    if not rows:
        return expected_on_hand == 0
    return rows[0]["on_hand"] == expected_on_hand
