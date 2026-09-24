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


def bootstrap(base_url: str) -> dict:
    _wait_for_openfga(base_url)
    model_json = _transform_model_to_json(AUTH_DIR / "model.fga")
    tuples = yaml.safe_load((AUTH_DIR / "tuples.yaml").read_text())

    with httpx.Client(timeout=10.0) as client:
        store_id = _find_or_create_store(client, base_url, STORE_NAME)
        model_id = _write_model(client, base_url, store_id, model_json)
        written = _write_tuples(client, base_url, store_id, tuples)

    return {"store_id": store_id, "authorization_model_id": model_id, "tuples_written": written}


def main() -> int:
    import os

    base_url = os.environ.get("OPENFGA_API_URL")
    if not base_url:
        sys.path.insert(0, str(REPO_ROOT))
        from seed import db_env

        db_env.load_dotenv()
        base_url = db_env.openfga_api_url()

    result = bootstrap(base_url)
    print(f"[bootstrap_openfga] store={result['store_id']} "
          f"model={result['authorization_model_id']} "
          f"tuples_written_this_run={result['tuples_written']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
