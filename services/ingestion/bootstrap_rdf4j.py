#!/usr/bin/env python3
"""Idempotent RDF4J bootstrap: create the "oo" repository if missing, then
(re)load the versioned ontology and SHACL shapes from contracts/ into their
named graphs, clearing each graph first so a re-run always reflects exactly
what is on disk (phase3.md item 1: "make up must register them
idempotently" — applied here to the same spirit as the Debezium connector
registration).

Run by `make up` (see Makefile) after the stack reports healthy. Safe to
run repeatedly: repository creation is skip-if-exists; ontology/shapes
graphs are clear-then-reload every time.

Phase 8 step 0 fix: ONTOLOGY_DIR/SHAPES_DIR used to be hardcoded to "v1" —
RDF4J's ShaclSail was therefore ALWAYS enforcing the v1 shapes regardless
of what contracts/manifests/deployed_version.json's own "ontology"/"shapes"
pointers said (harmless only because v1/v2's decision-shape.ttl sh:in
enumeration happened to be byte-identical — no migration before this one
ever added or removed a status). Adding oo:GateUnavailable (v3) is the
first ontology/shapes change that actually NEEDS RDF4J to enforce the new
version, so this now reads both directories from
services/common/contract_versions.deployed_version() — the SAME
"never cache, re-read every call" source migrations/*/deploy.py already
edit. reload_ontology_and_shapes() is factored out so a migration's own
deploy.py (see migrations/v2_to_v3_gates/deploy.py) can re-run just this
step against an ALREADY-RUNNING stack, without re-creating the repository."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from services.common import rdf_graphs  # noqa: E402
from services.common.contract_versions import deployed_version  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402

REPO_CONFIG_PATH = REPO_ROOT / "contracts" / "rdf4j" / "v1" / "oo-repository-config.ttl"
CONTRACTS_ROOT = REPO_ROOT / "contracts"


def reload_ontology_and_shapes(client: RDF4JClient, ontology_dir: Path | None = None, shapes_dir: Path | None = None) -> bool:
    """(Re)loads the ontology + SHACL shapes graphs from the given
    directories (default: whatever contracts/manifests/deployed_version.json
    currently names for "ontology"/"shapes") and proves SHACL enforcement is
    live via the functional probe below. Returns `shapes_active`. Does NOT
    touch repository creation — callers that need that call bootstrap()."""
    live = deployed_version()
    ontology_dir = ontology_dir or (CONTRACTS_ROOT / "ontology" / live["ontology"])
    shapes_dir = shapes_dir or (CONTRACTS_ROOT / "shapes" / live["shapes"])

    print(f"[bootstrap_rdf4j] reloading ontology graph <{rdf_graphs.ONTOLOGY_GRAPH}> from {ontology_dir.relative_to(REPO_ROOT)}")
    client.clear_graph(rdf_graphs.ONTOLOGY_GRAPH)
    for ttl_path in sorted(ontology_dir.glob("*.ttl")):
        resp = client.add_turtle(ttl_path.read_text(), graph_iri=rdf_graphs.ONTOLOGY_GRAPH)
        resp.raise_for_status()
        print(f"[bootstrap_rdf4j]   loaded {ttl_path.relative_to(REPO_ROOT)}")

    print(f"[bootstrap_rdf4j] reloading SHACL shapes graph <{rdf_graphs.RDF4J_SHACL_SHAPES_GRAPH}> from {shapes_dir.relative_to(REPO_ROOT)}")
    client.clear_graph(rdf_graphs.RDF4J_SHACL_SHAPES_GRAPH)
    for ttl_path in sorted(shapes_dir.glob("*.ttl")):
        resp = client.add_turtle(ttl_path.read_text(), graph_iri=rdf_graphs.RDF4J_SHACL_SHAPES_GRAPH)
        resp.raise_for_status()
        print(f"[bootstrap_rdf4j]   loaded {ttl_path.relative_to(REPO_ROOT)}")

    ontology_size = client.size(rdf_graphs.ONTOLOGY_GRAPH)
    # NOTE (verified empirically): ShaclSail consumes triples added to the
    # reserved SHACL_SHAPE_GRAPH context into its OWN internal shapes
    # model rather than storing them as ordinary queryable graph data —
    # `client.size(RDF4J_SHACL_SHAPES_GRAPH)` and a `GRAPH <...> { }`
    # SPARQL query both correctly report 0 even when the shapes ARE active
    # (confirmed by POSTing a known-invalid oo:Decision and observing the
    # expected HTTP 409 immediately after a fresh load). So this script
    # reports success via the SAME functional probe instead of a
    # (structurally misleading) triple count.
    probe = client.add_turtle(
        '@prefix oo: <https://example.local/oo/> . oo:__bootstrap_probe a oo:Decision .',
    )
    shapes_active = probe.status_code == 409
    print(
        f"[bootstrap_rdf4j] done: ontology graph {ontology_size} triples; "
        f"SHACL enforcement active={shapes_active} (probed with an incomplete oo:Decision, expected HTTP 409)"
    )
    if not shapes_active:
        raise RuntimeError(
            f"SHACL shapes do not appear to be enforced after bootstrap (probe returned {probe.status_code}, expected 409)"
        )
    return shapes_active


def bootstrap(client: RDF4JClient) -> None:
    if client.repository_exists():
        print(f"[bootstrap_rdf4j] repository '{client.repository}' already exists — skipping creation")
    else:
        print(f"[bootstrap_rdf4j] creating repository '{client.repository}'")
        client.create_repository(REPO_CONFIG_PATH.read_text())

    reload_ontology_and_shapes(client)


def main() -> int:
    db_env.load_dotenv()
    base_url = db_env.rdf4j_server_url()
    client = RDF4JClient(base_url=base_url, repository="oo")
    try:
        bootstrap(client)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
