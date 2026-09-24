"""Shared fixtures for tests/integration/. These tests exercise the REAL
docker-compose stack (docs/adr/0001-lite-mode-for-phase-1.md's lite mode is
a Phase 1 concept only — Phase 2 integration tests always run against real
Postgres-backed services, never in-process fakes).

Requires `make up && make seed` to have been run first. If the stack isn't
reachable, every test using `erp_client`/`mes_client`/`wms_client` is
explicitly SKIPPED with a reason (never silently passed — common.md honesty
rule) rather than erroring out inscrutably on connection refused.
"""

from __future__ import annotations

import sys
from pathlib import Path

import time

import httpx
import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402

db_env.load_dotenv()
BASE_URLS = db_env.http_base_urls()

DEFAULT_TIMEOUT = httpx.Timeout(10.0)


def _reachable(url: str) -> bool:
    try:
        r = httpx.get(f"{url}/health", timeout=2.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def stack_up() -> bool:
    return all(_reachable(url) for url in BASE_URLS.values())


def _client_fixture(service: str):
    @pytest.fixture()
    def _fixture(stack_up: bool):
        if not stack_up:
            pytest.skip(
                f"stack not reachable at {BASE_URLS[service]} — run 'make up && make seed' first"
            )
        with httpx.Client(base_url=BASE_URLS[service], timeout=DEFAULT_TIMEOUT) as client:
            yield client

    return _fixture


erp_client = _client_fixture("erp")
mes_client = _client_fixture("mes")
wms_client = _client_fixture("wms")


@pytest.fixture()
def wms_client_factory(stack_up: bool):
    """A callable returning a brand-new httpx.Client per call, for
    concurrency tests that want N genuinely independent HTTP connections
    (tests/integration/test_wms_idempotency.py, test_wms_concurrency.py)
    rather than sharing one client instance across threads."""
    if not stack_up:
        pytest.skip(f"stack not reachable at {BASE_URLS['wms']} — run 'make up && make seed' first")

    def _make() -> httpx.Client:
        return httpx.Client(base_url=BASE_URLS["wms"], timeout=DEFAULT_TIMEOUT)

    return _make


@pytest.fixture()
def wms_faults_reset(wms_client: httpx.Client):
    """Clears any armed WMS fault before AND after the test, so fault tests
    never leak state into each other or into unrelated tests."""
    wms_client.post("/_test/faults/reset")
    yield
    wms_client.post("/_test/faults/reset")


# --- Phase 4: hot projections (docs/experiment/briefs/phase4.md) ---------


@pytest.fixture(scope="session")
def rdf4j_reachable() -> bool:
    try:
        r = httpx.get(f"{db_env.rdf4j_server_url()}/repositories/oo/size", timeout=2.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture()
def rdf4j_client(rdf4j_reachable: bool):
    if not rdf4j_reachable:
        pytest.skip("RDF4J 'oo' repository not reachable — run 'make up' first")
    client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    yield client
    client.close()


@pytest.fixture()
def ontology_hot_conn():
    """A fresh connection per test (never shared/pooled) to the ontology_hot
    database, via the host-mapped Postgres port — same convention as
    seed/load.py. Explicitly SKIPPED (never erroring inscrutably) if
    unreachable, matching this file's `erp_client`/etc. pattern."""
    try:
        conn = psycopg.connect(db_env.ontology_hot_dsn(), connect_timeout=3, autocommit=True)
    except psycopg.OperationalError as e:
        pytest.skip(f"ontology_hot database not reachable ({e}) — run 'make up' first")
    yield conn
    conn.close()


def wait_until(predicate, timeout_s: float = 20.0, interval_s: float = 0.5):
    """Polls `predicate()` (a zero-arg callable returning a truthy value on
    success) until it succeeds or `timeout_s` elapses, then returns its
    final (possibly falsy) result — used to wait for
    services/projection_builder's poll loop to converge after driving a
    change through the real ERP/MES/WMS APIs, never a fixed `time.sleep`."""
    deadline = time.monotonic() + timeout_s
    result = predicate()
    while not result and time.monotonic() < deadline:
        time.sleep(interval_s)
        result = predicate()
    return result


# --- Phase 5: decision service (docs/experiment/briefs/phase5.md) --------


@pytest.fixture(scope="session")
def decision_service_reachable() -> bool:
    return _reachable(db_env.decision_service_url())


@pytest.fixture()
def decision_client(decision_service_reachable: bool):
    if not decision_service_reachable:
        pytest.skip(
            f"decision_service not reachable at {db_env.decision_service_url()} — run 'make up' first"
        )
    with httpx.Client(base_url=db_env.decision_service_url(), timeout=DEFAULT_TIMEOUT) as client:
        yield client


@pytest.fixture()
def ingestion_client(stack_up: bool):
    """services/ingestion's health endpoint — Phase 5 fix (watermark-based
    evidence freshness): tests read `watermarks` from here directly to
    ASSERT that a propose() decision's freshness came from the pipeline
    watermark, not from a per-row timestamp. Reuses the `stack_up` fixture's
    reachability (ingestion is one of the services it already probes via
    `BASE_URLS`? no — ingestion has its own health port, so check directly)."""
    url = db_env.ingestion_health_url()
    if not _reachable(url):
        pytest.skip(f"ingestion health endpoint not reachable at {url} — run 'make up' first")
    with httpx.Client(base_url=url, timeout=DEFAULT_TIMEOUT) as client:
        yield client


def get_lot(client: httpx.Client, part: str, warehouse_id: str) -> dict:
    """Looks up one inventory lot by (part, warehouse_id) via the query-
    filtered list endpoint rather than assuming a lot_id naming convention
    (services/wms/db_ops.py::set_inventory_for_test mints its own
    LOT-TEST-<warehouse>-<part> ids for test-injected lots)."""
    rows = client.get("/inventory_lots", params={"part": part, "warehouse_id": warehouse_id}).json()
    assert len(rows) == 1, f"expected exactly one lot for part={part} warehouse_id={warehouse_id}, got {rows}"
    return rows[0]
