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

Freshness (`max_evidence_freshness_s: 5` on transfer_inventory, matching
seed/fixtures/canonical_incident.yaml's `policy_config`) is asserted by
directly bumping `as_of` via SQL to `now()` IMMEDIATELY before propose() —
the mirror-image of test_projection_staleness.py's technique — because the
live `services/projection_builder` poll loop only re-derives `as_of` from
the real `oo:SourcePosition` every ~3s, and a real CDC round trip can itself
take longer than the 5s window being tested.
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
    waits for the change to converge into the `current_inventory` hot
    projection under its resolved CANONICAL id (real CDC + identity
    resolution + projection-builder round trip — no shortcuts on VALUE
    correctness), then bumps that row's `as_of` to `now()` so it is
    guaranteed FRESH the instant this returns. Callers must call propose()
    immediately after, with no sleep in between. Returns the canonical part
    id to use in the propose() request."""
    canonical = sku_to_canonical(sku)
    resp = wms_client.post(
        "/_test/inventory/set",
        json={"part": sku, "warehouse_id": warehouse_id, "on_hand": on_hand, "reserved": reserved, "quality_status": quality_status},
    )
    assert resp.status_code == 200, f"_test/inventory/set failed: {resp.status_code} {resp.text}"

    row = wait_until(lambda: reader.get_current_inventory(conn, canonical, warehouse_id), timeout_s=timeout_s)
    assert row is not None, f"current_inventory row for canonical part={canonical} (sku={sku}) warehouse={warehouse_id} never converged"
    assert row["on_hand"] == on_hand, f"expected on_hand={on_hand}, hot projection shows {row['on_hand']} (stale read?)"

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE current_inventory SET as_of = now() WHERE part = %s AND warehouse = %s", (canonical, warehouse_id)
        )
    return canonical


def propose_with_freshness_retry(conn: psycopg.Connection, part: str, warehouse_id: str, propose_fn, max_attempts: int = 5) -> httpx.Response:
    """Re-bumps `as_of` to `now()` and re-calls `propose_fn()` up to
    `max_attempts` times if (and ONLY if) the response is specifically
    INSUFFICIENT_EVIDENCE due to a lost freshness race (`source_available_fresh`
    in `missing`) — never masks any OTHER outcome, so a test asserting a
    genuinely different status still fails loudly and immediately.

    Found empirically running the full suite against a FRESHLY reseeded
    stack (heavy CDC backlog just drained): `services/projection_builder`'s
    live poll loop rebuilds `current_inventory` from the REAL
    `oo:SourcePosition.lastObservedAt` every ~3s, reverting a test's manual
    `as_of = now()` bump the moment the next cycle lands. A single
    bump-then-call is a race against that cycle; retrying is far cheaper and
    more robust than trying to synchronize with the live poller's phase.
    Never used for the F08 staleness test, which deliberately WANTS a stale
    read and must not retry past it."""
    response = None
    for _ in range(max_attempts):
        with conn.cursor() as cur:
            cur.execute("UPDATE current_inventory SET as_of = now() WHERE part = %s AND warehouse = %s", (part, warehouse_id))
        response = propose_fn()
        if response.status_code != 200:
            return response
        body = response.json()
        if body.get("status") == "INSUFFICIENT_EVIDENCE" and "source_available_fresh" in body.get("evidence_snapshot", {}).get("missing", []):
            continue
        return response
    return response


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
