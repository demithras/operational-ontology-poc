"""Shared fixtures for tests/contracts/ (Phase 3 — SHACL contract tests).

Level 1 tests (docs/experiment/spec/08_test_strategy.md "Contract/unit
tests") load the versioned ontology + shapes straight off disk with rdflib/
pyshacl — no docker stack required. A second, transactional layer
(test_shacl_rdf4j_transactional.py) additionally proves the SAME shapes
reject writes inside the real RDF4J "oo" repository (phase3.md item 2:
"invalid governed writes FAIL THE TRANSACTION"); those tests are skipped
with an explicit reason if the stack/repository isn't reachable, never
silently passed (common.md honesty rule).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import rdflib

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402

db_env.load_dotenv()

ONTOLOGY_DIR = REPO_ROOT / "contracts" / "ontology" / "v1"
SHAPES_DIR = REPO_ROOT / "contracts" / "shapes" / "v1"
POSITIVE_DIR = REPO_ROOT / "tests" / "contracts" / "shacl" / "positive"
NEGATIVE_DIR = REPO_ROOT / "tests" / "contracts" / "shacl" / "negative"


def _load_dir(directory: Path) -> rdflib.Graph:
    g = rdflib.Graph()
    for path in sorted(directory.glob("*.ttl")):
        g.parse(path, format="turtle")
    return g


@pytest.fixture(scope="session")
def ontology_graph() -> rdflib.Graph:
    return _load_dir(ONTOLOGY_DIR)


@pytest.fixture(scope="session")
def shapes_graph() -> rdflib.Graph:
    return _load_dir(SHAPES_DIR)


def positive_fixtures() -> list[Path]:
    return sorted(POSITIVE_DIR.glob("*.ttl"))


def negative_fixtures() -> list[Path]:
    return sorted(NEGATIVE_DIR.glob("*.ttl"))
