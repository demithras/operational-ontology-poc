#!/usr/bin/env python3
"""`make deploy-v3` — the V2 -> V3 contract redeploy (docs/experiment/spec/07_versioning_and_replay.md
"a second incompatible evolution of your choice").

Order:
  1. migrate_authz.py — publish contracts/authorization/v2/model.fga as a
     new model in the live OpenFGA store + migrate supervisor-1's approval
     authority forward (see that module's docstring).
  2. Flip contracts/manifests/deployed_version.json's "actions" -> "v3" and
     "authorization" -> "v2" (per-kind independent numbering — this
     experiment's OTHER kinds, ontology/shapes/policies/projections, are
     untouched at V3; see docs/experiment/implementation-notes.md Phase 7
     section for why).

No projection rebuild step here (unlike migrations/v1_to_v2/deploy.py) —
V3 touches neither the RDF observed graph nor any projection definition.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from migrations.v2_to_v3.migrate_authz import migrate as migrate_authz  # noqa: E402
from seed import db_env  # noqa: E402

DEPLOYED_VERSION_PATH = REPO_ROOT / "contracts" / "manifests" / "deployed_version.json"


def deploy() -> dict:
    db_env.load_dotenv()
    authz_result = migrate_authz(db_env.openfga_api_url())

    current = json.loads(DEPLOYED_VERSION_PATH.read_text())
    before_version = dict(current)
    current["actions"] = "v3"
    current["authorization"] = "v2"
    DEPLOYED_VERSION_PATH.write_text(json.dumps(current, indent=2, sort_keys=False) + "\n")

    return {
        "new_authorization_model_id": authz_result["authorization_model_id"],
        "deployed_version_before": before_version,
        "deployed_version_after": current,
    }


def main() -> int:
    result = deploy()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
