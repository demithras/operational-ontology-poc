"""Shared fixtures for tests/replay/ (Phase 7). Reuses
tests/integration/conftest.py's own rdf4j_client/ontology_hot_conn/
decision_client fixtures directly (pytest fixtures are plain importable
functions) rather than a second hand-rolled copy of the same skip-if-
unreachable logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from seed import db_env
from tests.integration.conftest import (  # noqa: F401
    decision_client, decision_service_reachable, ontology_hot_conn, rdf4j_client, rdf4j_reachable, stack_up,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "historical-corpus.json"


@pytest.fixture(scope="session")
def historical_corpus() -> dict:
    if not CORPUS_PATH.exists():
        pytest.skip(
            f"{CORPUS_PATH} does not exist — run seed/generators/historical_corpus.py "
            "for --version v1 and --version v2 first (see docs/experiment/implementation-notes.md Phase 7 section)"
        )
    return json.loads(CORPUS_PATH.read_text())


@pytest.fixture()
def openfga_api_url() -> str:
    db_env.load_dotenv()
    return db_env.openfga_api_url()
