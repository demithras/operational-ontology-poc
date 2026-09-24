#!/usr/bin/env python3
"""`make deploy-v3-gates` — Phase 8 step 0's contract redeploy: publishes
oo:GateUnavailable (docs/experiment/spec/11_acceptance_criteria.md
criterion A.11 — "component failure causes explicit unavailable/pending/
unknown state, not fabricated certainty") into the ontology/shapes
enumeration.

Unlike migrations/v1_to_v2/ (retires a property) and migrations/v2_to_v3/
(a new, non-inherited authorization relation), this migration is PURELY
ADDITIVE: one new skos:Concept + one new sh:in member. No existing triple,
property, or shape rule changes — contracts/ontology/v2/ and
contracts/shapes/v2/ are byte-for-byte untouched, so every decision already
pinned to "v2@sha256:..." for either kind keeps replaying against that
exact archived content (services/decision_service/replay.py::_verify_archive)
with no re-generation needed.

Order:
  1. reload_ontology_and_shapes() — RDF4J's ShaclSail only enforces
     whatever was last loaded into its ontology/shapes graphs
     (services/ingestion/bootstrap_rdf4j.py at `make up` time) — a data-only
     edit to deployed_version.json alone (step 2) would NOT make oo:status
     oo:GateUnavailable writable; it would still 409 against whatever shapes
     are currently loaded. Do this FIRST so the flip in step 2 never
     publishes a version the live repository cannot actually enforce yet.
  2. Flip contracts/manifests/deployed_version.json's "ontology"/"shapes"
     pointers to "v3" — services/decision_service/manifest.py (and hence
     every NEW decision's pinned ontology_version/shape_set_version) picks
     this up live, no decision_service restart required (same pattern as
     migrations/v1_to_v2/deploy.py and migrations/v2_to_v3/deploy.py).

No projection rebuild step (unlike migrations/v1_to_v2/deploy.py) — this
migration touches no fac: predicate or projection-relevant triple.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.ingestion.bootstrap_rdf4j import reload_ontology_and_shapes  # noqa: E402

DEPLOYED_VERSION_PATH = REPO_ROOT / "contracts" / "manifests" / "deployed_version.json"
CONTRACTS_ROOT = REPO_ROOT / "contracts"


def deploy() -> dict:
    db_env.load_dotenv()

    rdf_client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    try:
        shapes_active = reload_ontology_and_shapes(
            rdf_client,
            ontology_dir=CONTRACTS_ROOT / "ontology" / "v3",
            shapes_dir=CONTRACTS_ROOT / "shapes" / "v3",
        )
    finally:
        rdf_client.close()

    current = json.loads(DEPLOYED_VERSION_PATH.read_text())
    before_version = dict(current)
    current["ontology"] = "v3"
    current["shapes"] = "v3"
    DEPLOYED_VERSION_PATH.write_text(json.dumps(current, indent=2, sort_keys=False) + "\n")

    return {
        "shapes_active": shapes_active,
        "deployed_version_before": before_version,
        "deployed_version_after": current,
    }


def main() -> int:
    result = deploy()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
