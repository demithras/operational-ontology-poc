"""`make up` (Makefile, run BEFORE services/decision_service/bootstrap_openfga.py):
resets contracts/manifests/deployed_version.json to the tracked V1 baseline
(contracts/manifests/baseline_v1.json) whenever the stack is GENUINELY
FRESH — the `ontology_hot.decisions` table has zero rows, true right after
`make reset`'s `docker compose down -v` (or the very first `make up` an
environment ever runs).

Root cause this fixes (found live during the Phase 7b corpus
regeneration, docs/experiment/briefs/phase7b.md orchestrator direction
item 1): `contracts/manifests/deployed_version.json` is a HOST FILE, not a
Docker volume — `docker compose down -v` wipes Postgres/RDF4J/OpenFGA
state but never touches this file. A fresh, genuinely v1-shaped stack was
therefore paired with a STALE deployed-version label left over from
whatever contract version a PRIOR session had last deployed (e.g. v3) —
and `seed/generators/historical_corpus.py --version v1` silently generated
decisions against the WRONG live contract version, since the --version
flag is cosmetic (SKU numbering / results.json key only) and does not
itself change what decision_service serves. 82 decisions were mislabeled
"v1" in the corpus this way before the bug was caught by a downstream
replay test asserting the wrong policyBundleVersion.

Deletes contracts/manifests/openfga_model_ids.json too, when resetting —
OpenFGA's own store lives in the SAME shared Postgres volume `down -v`
wipes, so any "v2"/"v3" model id already recorded there is equally stale
(pointing at a model id that no longer exists in the new store); running
BEFORE bootstrap_openfga.py in `make up` means that script writes a
completely clean file afterward, with no leftover stale keys.

Never fails `make up` over this check: DB-unreachable or
freshness-undetermined always leaves both files untouched (treated as
"not empty" — the conservative, non-destructive default) rather than
guessing.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOYED_VERSION_PATH = REPO_ROOT / "contracts" / "manifests" / "deployed_version.json"
BASELINE_PATH = REPO_ROOT / "contracts" / "manifests" / "baseline_v1.json"
MODEL_IDS_PATH = REPO_ROOT / "contracts" / "manifests" / "openfga_model_ids.json"


def _decisions_table_is_empty() -> bool | None:
    """None = could not determine (DB unreachable, or reachable but the
    `decisions` table genuinely doesn't exist yet — decision_service's own
    schema.sql creates it at startup, and `make up` only calls this AFTER
    `wait-healthy`, so a missing table at that point means "not up yet",
    not "definitely fresh" — safer to skip than to guess)."""
    sys.path.insert(0, str(REPO_ROOT))
    from seed import db_env
    import psycopg

    db_env.load_dotenv()
    try:
        with psycopg.connect(db_env.ontology_hot_dsn(), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.decisions')")
                if cur.fetchone()[0] is None:
                    return None
                cur.execute("SELECT count(*) FROM decisions")
                return cur.fetchone()[0] == 0
    except Exception as exc:  # noqa: BLE001 - never fail `make up` over this check
        print(
            f"[reset_deployed_version_if_empty] could not determine freshness ({type(exc).__name__}: {exc}) "
            "-- skipping, leaving deployed_version.json untouched",
        )
        return None


def main() -> int:
    empty = _decisions_table_is_empty()
    if not empty:
        print("[reset_deployed_version_if_empty] decisions table has rows (or freshness undetermined) -- deployed_version.json left as-is")
        return 0

    if not BASELINE_PATH.exists():
        print(
            f"[reset_deployed_version_if_empty] WARNING: {BASELINE_PATH} missing -- cannot reset to baseline, "
            "leaving deployed_version.json untouched",
            file=sys.stderr,
        )
        return 0

    shutil.copyfile(BASELINE_PATH, DEPLOYED_VERSION_PATH)
    print(f"[reset_deployed_version_if_empty] fresh stack detected (0 decisions) -- reset {DEPLOYED_VERSION_PATH.name} to the tracked V1 baseline")

    if MODEL_IDS_PATH.exists():
        MODEL_IDS_PATH.unlink()
        print(f"[reset_deployed_version_if_empty] removed stale {MODEL_IDS_PATH.name} -- bootstrap_openfga.py (next in `make up`) will write a clean one")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
