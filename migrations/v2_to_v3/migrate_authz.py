#!/usr/bin/env python3
"""V2 -> V3 authorization migration (docs/experiment/spec/07_versioning_and_replay.md
"a second incompatible evolution of your choice" -- this experiment's choice
is an authorization-model change, see contracts/authorization/v2/model.fga's
header and docs/adr/0004-openfga-historical-model-and-tuple-snapshot.md).

Publishes contracts/authorization/v2/model.fga as a BRAND NEW authorization
model in the SAME live OpenFGA store (reusing
services/decision_service/bootstrap_openfga.py's own transform-and-write
logic — models are immutable-by-id and additive, so v1's model is never
touched) and writes contracts/authorization/v2/tuples.yaml's tuples,
including the one genuinely MIGRATED tuple (supervisor-1's authority
carried forward into the new senior_approver relation) — without it, every
existing v1 supervisor would silently lose V2 approval authority, exactly
the kind of "breaking change without migration" F28/scripts/compat_check.py
exists to catch.

Records the new model's real id into contracts/manifests/openfga_model_ids.json
under key "v2" — services/decision_service/manifest.py reads this to attach
`authorization_model_id` onto every future Decision once deployed_version.json's
"authorization" pointer moves to "v2".
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from seed import db_env  # noqa: E402
from services.decision_service.bootstrap_openfga import _record_model_id, bootstrap  # noqa: E402

AUTH_V2_DIR = REPO_ROOT / "contracts" / "authorization" / "v2"


def migrate(base_url: str) -> dict:
    result = bootstrap(base_url, auth_dir=AUTH_V2_DIR)
    _record_model_id("v2", result["authorization_model_id"])
    return result


def main() -> int:
    db_env.load_dotenv()
    result = migrate(db_env.openfga_api_url())
    print(f"[migrate_authz v2_to_v3] store={result['store_id']} "
          f"new_authorization_model_id={result['authorization_model_id']} "
          f"tuples_written_this_run={result['tuples_written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
