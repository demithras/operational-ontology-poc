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

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402

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


def get_lot(client: httpx.Client, part: str, warehouse_id: str) -> dict:
    """Looks up one inventory lot by (part, warehouse_id) via the query-
    filtered list endpoint rather than assuming a lot_id naming convention
    (services/wms/db_ops.py::set_inventory_for_test mints its own
    LOT-TEST-<warehouse>-<part> ids for test-injected lots)."""
    rows = client.get("/inventory_lots", params={"part": part, "warehouse_id": warehouse_id}).json()
    assert len(rows) == 1, f"expected exactly one lot for part={part} warehouse_id={warehouse_id}, got {rows}"
    return rows[0]
