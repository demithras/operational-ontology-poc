"""F19 (duplicate CDC -> idempotent, no state change), F20 (reordered CDC ->
no invariant break; ordering by LSN/version), F35 (clock skew -> ordering
relies on source LSN/versions, never wall clock).

Exercises services.ingestion.store.IngestionStore.apply_event DIRECTLY
against the REAL running RDF4J repository — the exact same function
services/ingestion/consumer.py calls per real Debezium message
(services/ingestion/consumer.py::process_message). This is a deliberate,
documented choice over fabricating raw Kafka/Debezium byte envelopes: the
CDC envelope format is Debezium's own implementation detail, not part of
the idempotency/ordering contract under test, and driving apply_event
directly is deterministic (no Kafka delivery-timing races) while proving
the identical code path. F19 has additional coverage at
tests/integration/test_cdc_ingestion.py::test_duplicate_cdc_event_is_idempotent
(same technique, mirrored here so F19 is ALSO exercised under `make
test-faults` per this phase's brief); F20/F35 are new.

A synthetic lot id per test keeps this fully independent of any other
test's or the live pipeline's state (never the canonical fixture).
"""

from __future__ import annotations

import uuid

from services.common.rdf4j_client import RDF4JClient
from services.identity_resolver.resolver import IdentityResolver
from services.ingestion import mapping, store
from services.ingestion.lsn import lsn_to_int, ordering_key


def _select_one(rdf4j_client: RDF4JClient, subject: str) -> dict[str, str]:
    query = f"""
    SELECT ?p ?o WHERE {{
      GRAPH <https://example.local/oo/graph/observed> {{ <{subject}> ?p ?o }}
    }}
    """
    rows = rdf4j_client.select(query)
    return {row["p"]: row["o"] for row in rows}


def _apply_lot_event(
    ing_store: store.IngestionStore, resolver: IdentityResolver, lot_id: str, on_hand: int, source_lsn: str, source_version: int
) -> dict:
    row = {"lot_id": lot_id, "part": "SKU-88429", "warehouse_id": "WH-A", "on_hand": on_hand, "reserved": 0, "quality_status": "OK"}
    mapped = mapping.map_row("wms", "inventory_lots", row, resolver)
    entity_iri = mapping.resolve_entity_iri("wms", "inventory_lots", lot_id, resolver)
    return ing_store.apply_event("wms", "inventory_lots", lot_id, "u", entity_iri, mapped, source_lsn=source_lsn, source_version=source_version)


# --- F19: duplicate CDC delivery does not change state ---------------------


def test_f19_duplicate_cdc_event_is_idempotent(rdf4j_client: RDF4JClient):
    resolver = IdentityResolver()
    ing_store = store.IngestionStore(rdf4j_client)
    lot_id = f"LOT-F19-{uuid.uuid4().hex[:8]}"
    subject = f"https://example.local/factory/instance/InventoryLot/{lot_id}"
    try:
        r1 = _apply_lot_event(ing_store, resolver, lot_id, on_hand=77, source_lsn="0/A00001", source_version=1)
        assert r1["applied"] is True

        r2 = _apply_lot_event(ing_store, resolver, lot_id, on_hand=77, source_lsn="0/A00001", source_version=1)
        assert r2["applied"] is False
        assert r2["reason"] == "stale_or_duplicate"

        state = _select_one(rdf4j_client, subject)
        assert state.get("https://example.local/factory/onHand") == "77"
    finally:
        rdf4j_client.delete_subject(subject, graph_iri="https://example.local/oo/graph/observed")


# --- F20: reordered CDC delivery still converges to the LATEST-by-LSN value


def test_f20_reordered_cdc_delivery_resolves_by_lsn_not_delivery_order(rdf4j_client: RDF4JClient):
    resolver = IdentityResolver()
    ing_store = store.IngestionStore(rdf4j_client)
    lot_id = f"LOT-F20-{uuid.uuid4().hex[:8]}"
    subject = f"https://example.local/factory/instance/InventoryLot/{lot_id}"
    try:
        # Event B (LSN 200, the REAL later state) is delivered FIRST — a
        # genuine Kafka/Debezium reordering scenario.
        r_b_first = _apply_lot_event(ing_store, resolver, lot_id, on_hand=200, source_lsn="0/C8", source_version=1)
        assert r_b_first["applied"] is True

        # Event A (LSN 100, an OLDER state) arrives SECOND — must be
        # rejected as stale, never overwrite the newer value, regardless of
        # arrival order.
        r_a_second = _apply_lot_event(ing_store, resolver, lot_id, on_hand=100, source_lsn="0/64", source_version=1)
        assert r_a_second["applied"] is False
        assert r_a_second["reason"] == "stale_or_duplicate"

        state = _select_one(rdf4j_client, subject)
        assert state.get("https://example.local/factory/onHand") == "200", (
            "F20: the invariant (never regress to an older source position) broke under reordered delivery"
        )
    finally:
        rdf4j_client.delete_subject(subject, graph_iri="https://example.local/oo/graph/observed")


# --- F35: ordering relies on source LSN/version, never wall clock ----------


def test_f35_ordering_key_ignores_wall_clock_uses_lsn_and_version():
    """Pure unit proof at the ordering-key level (services/ingestion/lsn.py
    takes no timestamp parameter at all — there is no wall-clock input to
    even inject skew into, which IS the property F35 requires). A later LSN
    always compares greater, independent of anything about when either
    event was produced or observed."""
    key_earlier_lsn = ordering_key(source_lsn="0/64", source_version=1)  # lsn=100
    key_later_lsn = ordering_key(source_lsn="0/C8", source_version=1)  # lsn=200
    assert key_later_lsn > key_earlier_lsn

    # None (skew/missing clock — a snapshot read before a real LSN exists)
    # sorts as the LOWEST possible position, never as "newer".
    assert lsn_to_int(None) == 0
    assert ordering_key(None, 1) < key_earlier_lsn


def test_f35_apply_event_end_to_end_with_out_of_order_wall_clock_but_correct_lsn(rdf4j_client: RDF4JClient):
    """Same mechanism as F20's test, framed explicitly around clock skew:
    two events are applied in an order where a naive "latest wall-clock
    timestamp wins" implementation would pick the WRONG one (the earlier-
    LSN event is fabricated with a LATER-looking artificial timestamp
    embedded nowhere the ingestion code ever reads it — apply_event has no
    timestamp parameter at all, so this test also documents BY CONSTRUCTION
    that no such input exists to be skewed)."""
    resolver = IdentityResolver()
    ing_store = store.IngestionStore(rdf4j_client)
    lot_id = f"LOT-F35-{uuid.uuid4().hex[:8]}"
    subject = f"https://example.local/factory/instance/InventoryLot/{lot_id}"
    try:
        # The TRUE-later event (higher LSN) is applied first here too, to
        # keep this independent of any incidental store.py caching between
        # tests; the point under test is purely that a SUBSEQUENT lower-LSN
        # event — however "recent" its wall-clock arrival might look to a
        # naive observer — cannot regress the observed state.
        r_newer = _apply_lot_event(ing_store, resolver, lot_id, on_hand=555, source_lsn="0/1000", source_version=5)
        assert r_newer["applied"] is True
        r_older_but_delivered_later = _apply_lot_event(ing_store, resolver, lot_id, on_hand=111, source_lsn="0/200", source_version=1)
        assert r_older_but_delivered_later["applied"] is False

        state = _select_one(rdf4j_client, subject)
        assert state.get("https://example.local/factory/onHand") == "555"
    finally:
        rdf4j_client.delete_subject(subject, graph_iri="https://example.local/oo/graph/observed")
