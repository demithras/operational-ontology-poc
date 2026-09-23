#!/usr/bin/env python3
"""Idempotently register the versioned Debezium Postgres connectors
(contracts/cdc/v1/*.json) with the running Kafka Connect REST API.

Run by `make up` after the stack reports healthy (phase3.md item 1: "make
up must register them idempotently"). PUT .../connectors/{name}/config is
itself idempotent (create-or-update), so this script is safe to re-run.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import httpx

from seed import db_env

CONNECTOR_CONFIG_DIR = REPO_ROOT / "contracts" / "cdc" / "v1"


def register_one(client: httpx.Client, connect_url: str, config_path: Path) -> None:
    spec = json.loads(config_path.read_text())
    name = spec["name"]
    config = spec["config"]
    resp = client.put(f"{connect_url}/connectors/{name}/config", json=config, timeout=30.0)
    resp.raise_for_status()
    print(f"[register_connectors] {config_path.name} -> connector {name!r}: HTTP {resp.status_code}")


def wait_for_connect(client: httpx.Client, connect_url: str, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = client.get(connect_url, timeout=3.0)
            if resp.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(2.0)
    raise TimeoutError(f"Kafka Connect not reachable at {connect_url} after {timeout_s}s")


def main() -> int:
    db_env.load_dotenv()
    connect_url = db_env.connect_rest_url()

    with httpx.Client() as client:
        wait_for_connect(client, connect_url)
        for config_path in sorted(CONNECTOR_CONFIG_DIR.glob("*-connector.json")):
            register_one(client, connect_url, config_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
