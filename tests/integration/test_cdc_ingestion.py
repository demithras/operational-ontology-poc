"""End-to-end CDC ingestion tests (phase3.md item 7's "tests/integration"
list): a WMS API change appears in RDF4J with provenance within a declared
convergence bound; duplicate CDC delivery doesn't change state; an invalid
governed write is rejected by the RDF4J SHACL transaction; stopping RDF4J
makes ingestion back off without data loss, and it resumes after restart.

Requires the FULL Phase 3 stack (`make up` — postgres/erp/mes/wms/kafka/
connect/rdf4j/ingestion all healthy, connectors registered, RDF4J
bootstrapped) and `make seed`. Every test here is explicitly SKIPPED with a
reason if that isn't the case (common.md honesty rule), same pattern as
tests/integration/conftest.py's stack_up fixture.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.identity_resolver.resolver import IdentityResolver  # noqa: E402
from services.ingestion import mapping, readiness, store  # noqa: E402

from tests.contracts.conftest import negative_fixtures  # noqa: E402

db_env.load_dotenv()

DOCKER_CONFIG_ENV = {
    "DOCKER_CONFIG": "/private/tmp/claude-501/-Users-d-surchis-work-operational-ontology-poc/"
    "4651d52d-5874-4c7c-ba8b-4da032dde2a5/scratchpad/docker-config"
}
CONVERGENCE_BOUND_S = 10.0
POLL_INTERVAL_S = 0.5


def _rdf4j_and_ingestion_up() -> bool:
    try:
        client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
        try:
            if not client.repository_exists():
                return False
        finally:
            client.close()
        r = httpx.get(f"{db_env.ingestion_health_url()}/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _rdf4j_and_ingestion_up(),
    reason="RDF4J 'oo' repository or ingestion health endpoint not reachable — run 'make up' first",
)


@pytest.fixture()
def rdf4j_client():
    client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    yield client
    client.close()


def _ingestion_health() -> dict:
    return httpx.get(f"{db_env.ingestion_health_url()}/health", timeout=5.0).json()


def _wait_for_ingestion_caught_up(timeout_s: float = 90.0) -> None:
    """Waits for the ingestion consumer group's committed Kafka offsets to
    reach each CDC topic's CURRENT high-watermark (services/ingestion/
    readiness.py — the phase4fix.md "single readiness contract" module).

    This REPLACES a prior implementation that polled the ingestion health
    endpoint's `messages_consumed` counter and declared success the moment
    two consecutive 2-second samples were equal. That was a stale notion of
    lag: it is satisfied just as happily by "nothing new has arrived at
    Kafka yet" as by "the backlog has actually been drained" — caught
    empirically (docs/experiment/implementation-notes.md Phase 4 fix
    section) right after `make seed`, when this function returned
    immediately (both samples equal because Debezium had not even read the
    new WAL records yet) and the canonical lot (LOT-A-PX17) was genuinely
    absent from RDF4J. Comparing against the REAL, freshly-fetched Kafka
    high-watermark instead of a moving/pausable counter closes that gap."""
    try:
        readiness.wait_for_zero_kafka_lag(_kafka_bootstrap_servers(), timeout_s=timeout_s)
    except readiness.ConvergenceTimeout:
        pytest.skip(f"ingestion consumer did not reach zero Kafka lag within {timeout_s}s (still consuming backlog)")


def _kafka_bootstrap_servers() -> str:
    return f"localhost:{os.environ['KAFKA_HOST_PORT']}"


def _select_one(rdf4j_client: RDF4JClient, subject: str) -> dict[str, str]:
    rows = rdf4j_client.select(
        f"SELECT ?p ?o WHERE {{ GRAPH <https://example.local/oo/graph/observed> {{ <{subject}> ?p ?o }} }}"
    )
    return {r["p"]: r["o"] for r in rows}


# --- WMS change converges to RDF4J with provenance, within bound ----------


def test_wms_change_converges_to_rdf4j_with_provenance(wms_client: httpx.Client, rdf4j_client: RDF4JClient):
    _wait_for_ingestion_caught_up()

    # A synthetic, non-canonical (part, warehouse) pair for this test's
    # marker lot — the SAME convention test_wms_concurrency.py /
    # test_wms_idempotency.py / test_wms_faults.py already use for their own
    # SKU-*-TEST markers, and exactly what
    # test_rdf4j_outage_backs_off_without_data_loss_and_resumes below does
    # ("a GENERATED (non-canonical-fixture) part/warehouse pair ... so this
    # test never mutates the canonical incident fixture's own PX-17/WH-A/
    # WH-B state"). This test originally targeted LOT-A-PX17/SKU-88429/WH-A
    # directly — the canonical fixture — which permanently drifted its
    # on_hand upward by 1 every time this test ran, breaking
    # test_canonical_scenario.py::test_step4's absolute-end-state assertion
    # (`after_a["on_hand"] == 80`) on any `make test` invocation that wasn't
    # preceded by a fresh `make reset && make seed` (docs/experiment/
    # implementation-notes.md Phase 4 fix section has the full write-up —
    # found while validating this exact phase4fix.md fix by running `make
    # test` repeatedly, which the acceptance criteria requires).
    marker_part = "SKU-CDC-CONVERGENCE-TEST"
    marker_warehouse = "WH-C"

    existing = wms_client.get("/inventory_lots", params={"part": marker_part, "warehouse_id": marker_warehouse}).json()
    before: dict[str, str] = {}
    if existing:
        before = _select_one(rdf4j_client, f"https://example.local/factory/instance/InventoryLot/{existing[0]['lot_id']}")
    new_on_hand = int(before.get("https://example.local/factory/onHand", "0")) + 1

    resp = wms_client.post(
        "/_test/inventory/set",
        json={"part": marker_part, "warehouse_id": marker_warehouse, "on_hand": new_on_hand, "reserved": 0, "quality_status": "OK"},
    )
    assert resp.status_code == 200
    # set_inventory_for_test upserts on (part, warehouse_id); read the
    # resulting lot_id back from the response rather than assuming a naming
    # convention (same reasoning as the outage test below).
    lot_id = resp.json()["lot_id"]
    lot_subject = f"https://example.local/factory/instance/InventoryLot/{lot_id}"

    deadline = time.monotonic() + CONVERGENCE_BOUND_S
    converged = False
    while time.monotonic() < deadline:
        state = _select_one(rdf4j_client, lot_subject)
        if state.get("https://example.local/factory/onHand") == str(new_on_hand):
            converged = True
            break
        time.sleep(POLL_INTERVAL_S)

    assert converged, (
        f"WMS change (on_hand={new_on_hand}) did not converge into RDF4J within "
        f"the {CONVERGENCE_BOUND_S}s bound"
    )

    # Provenance: at least one applied oo:Observation for this pk, sourced from wms.
    obs_rows = rdf4j_client.select(
        f"""
        SELECT ?applied WHERE {{
          GRAPH <https://example.local/oo/graph/provenance> {{
            ?obs a <https://example.local/oo/Observation> ;
                 <https://example.local/oo/sourceSystem> "wms" ;
                 <https://example.local/oo/sourceTable> "inventory_lots" ;
                 <https://example.local/oo/sourcePk> "{lot_id}" ;
                 <https://example.local/oo/applied> ?applied .
          }}
        }}
        """
    )
    assert any(row["applied"] == "true" for row in obs_rows), "no applied Observation provenance record found"


# --- duplicate CDC delivery does not change state (F19) --------------------


def test_duplicate_cdc_event_is_idempotent(rdf4j_client: RDF4JClient):
    """Exercises services.ingestion.store.IngestionStore directly against
    the REAL running RDF4J repository (a Level-3 "real containers, real
    network" integration test per 08_test_strategy.md, even though it
    doesn't fabricate a raw Kafka/Debezium byte payload — that envelope
    format is Debezium's implementation detail, not part of the idempotency
    contract under test here). A synthetic lot id keeps this fully
    independent of any other test's or the live pipeline's state."""
    resolver = IdentityResolver()
    ing_store = store.IngestionStore(rdf4j_client)
    lot_id = f"LOT-DUP-TEST-{uuid.uuid4().hex[:8]}"
    subject = f"https://example.local/factory/instance/InventoryLot/{lot_id}"

    row = {"lot_id": lot_id, "part": "SKU-88429", "warehouse_id": "WH-A", "on_hand": 42, "reserved": 0, "quality_status": "OK"}
    mapped = mapping.map_row("wms", "inventory_lots", row, resolver)
    entity_iri = mapping.resolve_entity_iri("wms", "inventory_lots", lot_id, resolver)

    try:
        r1 = ing_store.apply_event("wms", "inventory_lots", lot_id, "u", entity_iri, mapped, source_lsn="0/900001", source_version=1)
        assert r1["applied"] is True

        # Deliver the IDENTICAL event again (same lsn/version) — the
        # duplicate-delivery scenario CDC/Kafka at-least-once semantics
        # produce (F19).
        r2 = ing_store.apply_event("wms", "inventory_lots", lot_id, "u", entity_iri, mapped, source_lsn="0/900001", source_version=1)
        assert r2["applied"] is False
        assert r2["reason"] == "stale_or_duplicate"

        state = _select_one(rdf4j_client, subject)
        assert state.get("https://example.local/factory/onHand") == "42"
    finally:
        rdf4j_client.delete_subject(subject, graph_iri="https://example.local/oo/graph/observed")


# --- invalid governed write rejected by RDF4J's SHACL transaction ----------


def test_invalid_governed_write_rejected_by_transaction(rdf4j_client: RDF4JClient):
    """Thin cross-reference at the integration level — the exhaustive
    positive/negative matrix lives in
    tests/contracts/test_shacl_rdf4j_transactional.py; this proves the same
    property holds against the SAME long-lived "oo" repository instance
    the rest of this file's tests run against (not a throwaway one)."""
    fixture = negative_fixtures()[0]
    graph = f"https://example.local/oo/graph/test/{uuid.uuid4()}"
    try:
        resp = rdf4j_client.add_turtle(fixture.read_text(), graph_iri=graph)
        assert resp.status_code == 409
        assert rdf4j_client.size(graph) == 0
    finally:
        rdf4j_client.clear_graph(graph)


# --- RDF4J down: ingestion backs off without data loss, resumes -----------


def _docker_compose(*args: str, timeout: float = 60.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        env={**os.environ, **DOCKER_CONFIG_ENV},
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_rdf4j_outage_backs_off_without_data_loss_and_resumes(wms_client: httpx.Client, rdf4j_client: RDF4JClient):
    _wait_for_ingestion_caught_up()

    stop = _docker_compose("stop", "rdf4j")
    if stop.returncode != 0:
        pytest.skip(f"could not stop rdf4j container (docker compose unavailable in this environment): {stop.stderr}")

    # A GENERATED (non-canonical-fixture) part/warehouse pair — SKU-100007
    # (i=7, resolves to PX-0007) in WH-C — with a distinctive on_hand value,
    # so this test never mutates the canonical incident fixture's own
    # PX-17/WH-A/WH-B state that other tests (and a human re-reading the
    # canonical scenario) reasonably expect to stay stable.
    marker_on_hand = 90000 + (uuid.uuid4().int % 1000)

    try:
        resp = wms_client.post(
            "/_test/inventory/set",
            json={"part": "SKU-100007", "warehouse_id": "WH-C", "on_hand": marker_on_hand, "reserved": 0, "quality_status": "OK"},
        )
        assert resp.status_code == 200
        # set_inventory_for_test upserts on (part, warehouse_id); the
        # resulting lot_id depends on whether a row already existed for
        # that pair (seeded data often already does), so read it back from
        # the response rather than assuming a naming convention.
        outage_lot_id = resp.json()["lot_id"]
        outage_subject = f"https://example.local/factory/instance/InventoryLot/{outage_lot_id}"

        time.sleep(5.0)
        health_during_outage = _ingestion_health()
        assert health_during_outage["last_error"], "expected ingestion to report an error while RDF4J is down"
    finally:
        start = _docker_compose("start", "rdf4j")
        assert start.returncode == 0, f"failed to restart rdf4j: {start.stderr}"
        # Wait for RDF4J's own healthcheck, then for ingestion to resume.
        deadline = time.monotonic() + 60.0
        rdf4j_back = False
        while time.monotonic() < deadline:
            try:
                if rdf4j_client.repository_exists():
                    rdf4j_back = True
                    break
            except Exception:
                pass
            time.sleep(2.0)
        assert rdf4j_back, "RDF4J did not come back up within 60s of 'docker compose start rdf4j'"

    # No data loss: the change made during the outage must still converge
    # now that RDF4J is back (ingestion retried the same un-committed
    # Kafka offset the whole time it was down).
    deadline = time.monotonic() + 30.0
    converged = False
    while time.monotonic() < deadline:
        state = _select_one(rdf4j_client, outage_subject)
        if state.get("https://example.local/factory/onHand") == str(marker_on_hand):
            converged = True
            break
        time.sleep(POLL_INTERVAL_S)
    assert converged, "change made during the RDF4J outage was lost instead of resuming after restart"
