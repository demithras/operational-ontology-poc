"""Level 1+ SHACL test: proves the REAL RDF4J "oo" repository (not just
pyshacl in-process) rejects invalid governed writes at the transaction
level (phase3.md item 2: "invalid governed writes FAIL THE TRANSACTION
(commit rejected)"; F07 in docs/experiment/spec/09_failure_and_adversarial_matrix.md).

Requires `make up` (RDF4J reachable) and
`python3 services/ingestion/bootstrap_rdf4j.py` (repository + ontology +
shapes loaded) to have been run first — skipped with an explicit reason
otherwise (common.md honesty rule), same pattern as
tests/integration/conftest.py's stack_up fixture.

Uses each fixture's own graph, cleaned up after the test, so this test
never leaves committed junk data behind (positive fixtures DO commit) or
collides with a concurrent run.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402

from tests.contracts.conftest import negative_fixtures, positive_fixtures  # noqa: E402

db_env.load_dotenv()


def _rdf4j_reachable() -> bool:
    try:
        client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
        try:
            return client.repository_exists()
        finally:
            client.close()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _rdf4j_reachable(),
    reason="RDF4J 'oo' repository not reachable — run 'make up' then "
    "'.venv/bin/python services/ingestion/bootstrap_rdf4j.py' first",
)


@pytest.fixture()
def rdf4j_client():
    client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    yield client
    client.close()


@pytest.mark.parametrize("fixture_path", positive_fixtures(), ids=lambda p: p.name)
def test_positive_fixture_commits(rdf4j_client: RDF4JClient, fixture_path: Path):
    # Fixtures use fixed IRIs (oo-fx:...) — isolate this run's copy into a
    # throwaway graph so repeated CI runs / parallel test sessions never
    # collide, then clean it up unconditionally.
    graph = f"https://example.local/oo/graph/test/{uuid.uuid4()}"
    try:
        resp = rdf4j_client.add_turtle(fixture_path.read_text(), graph_iri=graph)
        assert resp.status_code in (200, 204), (
            f"{fixture_path.name} was expected to be ACCEPTED by RDF4J's SHACL "
            f"transaction but got {resp.status_code}:\n{resp.text}"
        )
        assert rdf4j_client.size(graph) > 0, "committed fixture produced no triples in its graph"
    finally:
        rdf4j_client.clear_graph(graph)


@pytest.mark.parametrize("fixture_path", negative_fixtures(), ids=lambda p: p.name)
def test_negative_fixture_rejected_by_transaction(rdf4j_client: RDF4JClient, fixture_path: Path):
    graph = f"https://example.local/oo/graph/test/{uuid.uuid4()}"
    try:
        resp = rdf4j_client.add_turtle(fixture_path.read_text(), graph_iri=graph)
        assert resp.status_code == 409, (
            f"{fixture_path.name} was expected to be REJECTED (HTTP 409, commit "
            f"rejected per phase3.md item 2) but got {resp.status_code}:\n{resp.text}"
        )
        # The whole point of a *transactional* rejection: nothing committed.
        assert rdf4j_client.size(graph) == 0, (
            f"{fixture_path.name} was rejected with 409 but still left "
            f"{rdf4j_client.size(graph)} triples committed in its graph — "
            f"transaction was not actually atomic."
        )
    finally:
        rdf4j_client.clear_graph(graph)
