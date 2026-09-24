"""Idempotent OpenFGA bootstrap — run by `make up`, same pattern as
services/ingestion/bootstrap_rdf4j.py: safe to re-run against an already
bootstrapped server.

OpenFGA runs with the `memory` datastore engine (docker-compose.yml) —
state does not survive a container restart, so this always re-creates the
store/model/tuples fresh after `make reset`; within one running container's
lifetime it is idempotent (reuses the existing "oo-poc" store by name,
appends a new authorization-model VERSION each run — harmless, OpenFGA
keeps every version and Checks always use the latest unless pinned — and
tolerates "tuple already exists" on re-applied fixture tuples).

The .fga DSL -> JSON transform has no Python-side implementation in this
repo (avoiding a hand-written DSL parser); it shells out to the openfga/cli
docker image's `model transform` subcommand, which needs no network access
(pure local file transform) and was verified by hand during implementation
(`docker run --rm -v <dir>:/app openfga/cli:latest model transform
--file /app/model.fga --output-format json`).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTH_DIR = REPO_ROOT / "contracts" / "authorization" / "v1"
STORE_NAME = "oo-poc"


def _wait_for_openfga(base_url: str, timeout_s: float = 30.0) -> None:
    """OpenFGA's own readiness signal (verified empirically: GET /healthz
    returns {"status":"SERVING"} once the HTTP server is actually up) —
    docker-compose has no container-level healthcheck for this service (the
    image has neither a shell nor curl/wget, see docker-compose.yml's
    comment), so this is the real readiness proof."""
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    with httpx.Client(timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                r = client.get(f"{base_url}/healthz")
                if r.status_code == 200 and r.json().get("status") == "SERVING":
                    return
            except httpx.HTTPError as exc:
                last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"OpenFGA at {base_url} never became ready: {last_error}")


def _transform_model_to_json(model_path: Path) -> dict:
    result = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{model_path.parent}:/app:ro",
            "openfga/cli:latest",
            "model", "transform", "--file", f"/app/{model_path.name}", "--output-format", "json",
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"fga model transform failed: {result.stderr}")
    return json.loads(result.stdout)


def _find_or_create_store(client: httpx.Client, base_url: str, name: str) -> str:
    r = client.get(f"{base_url}/stores")
    r.raise_for_status()
    for store in r.json().get("stores", []):
        if store["name"] == name:
            return store["id"]
    r = client.post(f"{base_url}/stores", json={"name": name})
    r.raise_for_status()
    return r.json()["id"]


def _write_model(client: httpx.Client, base_url: str, store_id: str, model_json: dict) -> str:
    r = client.post(f"{base_url}/stores/{store_id}/authorization-models", json=model_json)
    r.raise_for_status()
    return r.json()["authorization_model_id"]


def _write_tuples(client: httpx.Client, base_url: str, store_id: str, tuples: list[dict]) -> int:
    written = 0
    for tuple_key in tuples:
        r = client.post(f"{base_url}/stores/{store_id}/write", json={"writes": {"tuple_keys": [tuple_key]}})
        if r.status_code == 200:
            written += 1
            continue
        if r.status_code == 400 and "already exist" in r.text.lower():
            continue  # idempotent re-apply of a fixture tuple already present
        r.raise_for_status()
    return written


def bootstrap(base_url: str, auth_dir: Path = AUTH_DIR) -> dict:
    """Phase 7: `auth_dir` lets migrations/v2_to_v3/migrate_authz.py reuse
    this SAME transform-and-write logic to publish a NEW authorization
    model (contracts/authorization/v2/model.fga) into the SAME store
    (OpenFGA models are immutable-by-id and additive — writing a new model
    version never touches/replaces v1's, which stays resolvable by its own
    id forever). Defaults to v1 exactly like every Phase 5/6 caller."""
    _wait_for_openfga(base_url)
    model_json = _transform_model_to_json(auth_dir / "model.fga")
    tuples = yaml.safe_load((auth_dir / "tuples.yaml").read_text())

    with httpx.Client(timeout=10.0) as client:
        store_id = _find_or_create_store(client, base_url, STORE_NAME)
        model_id = _write_model(client, base_url, store_id, model_json)
        written = _write_tuples(client, base_url, store_id, tuples)

    return {"store_id": store_id, "authorization_model_id": model_id, "tuples_written": written}


MODEL_IDS_PATH = REPO_ROOT / "contracts" / "manifests" / "openfga_model_ids.json"


def _record_model_id(version: str, model_id: str) -> None:
    """Phase 7: contracts/manifests/openfga_model_ids.json's "v1" entry —
    services/decision_service/manifest.py reads this to attach the REAL
    (immutable-by-id) OpenFGA authorization_model_id onto every Decision.
    Every `make up` re-bootstrap writes a NEW v1 model version (OpenFGA
    keeps every one; see this module's own docstring) — this always
    records the LATEST one, matching what `resolve_latest_authorization_model_id`
    would resolve live anyway, so decisions proposed right after any given
    `make up` stay consistent with what this file says "v1" currently
    means. A decision's OWN already-recorded id is never affected by a
    later overwrite here — see services/decision_service/models.py's
    openfga_authorization_model_id field, captured once per decision at
    propose() time."""
    model_ids = {}
    if MODEL_IDS_PATH.exists():
        try:
            model_ids = json.loads(MODEL_IDS_PATH.read_text())
        except json.JSONDecodeError:
            model_ids = {}
    model_ids[version] = model_id
    MODEL_IDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MODEL_IDS_PATH.write_text(json.dumps(model_ids, indent=2, sort_keys=True) + "\n")


def main() -> int:
    import os

    base_url = os.environ.get("OPENFGA_API_URL")
    if not base_url:
        sys.path.insert(0, str(REPO_ROOT))
        from seed import db_env

        db_env.load_dotenv()
        base_url = db_env.openfga_api_url()

    result = bootstrap(base_url)
    _record_model_id("v1", result["authorization_model_id"])
    print(f"[bootstrap_openfga] store={result['store_id']} "
          f"model={result['authorization_model_id']} "
          f"tuples_written_this_run={result['tuples_written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
