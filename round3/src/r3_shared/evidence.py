"""Evidence envelope writer (schemas/evidence-envelope.schema.json, docs/08)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

ROUND3 = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROUND3 / "schemas" / "evidence-envelope.schema.json"
FREEZE_PATH = ROUND3 / "protocol" / "FREEZE.json"


def canonical_bytes(x: Any) -> bytes:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_of(x: Any) -> str:
    return hashlib.sha256(canonical_bytes(x)).hexdigest()


def protocol_freeze_hash(path: Path = FREEZE_PATH) -> str:
    return json.loads(path.read_text())["protocol_sha256"]


def build_envelope(*, experiment_id: str, hypothesis_id: str, git_commit: str, environment: dict, seed: int | str,
                   attack_class: str, oracle_version: str, candidate_version: str, raw_observations: Any,
                   baseline_version: str | None = None, verdict: str | None = None,
                   freeze_hash: str | None = None, **extra: Any) -> dict:
    env = {"experiment_id": experiment_id, "hypothesis_id": hypothesis_id, "git_commit": git_commit,
           "protocol_freeze_hash": freeze_hash or protocol_freeze_hash(), "environment": environment, "seed": seed,
           "attack_class": attack_class, "oracle_version": oracle_version, "candidate_version": candidate_version,
           "baseline_version": baseline_version, "raw_observations": raw_observations, **extra}
    if verdict is not None:
        env["verdict"] = verdict
    env["payload_sha256"] = sha256_of({k: v for k, v in env.items() if k != "payload_sha256"})
    return env


def validate_envelope(env: dict) -> None:
    jsonschema.validate(env, json.loads(SCHEMA_PATH.read_text()))
    if "payload_sha256" in env:
        body = {k: v for k, v in env.items() if k != "payload_sha256"}
        if env["payload_sha256"] != sha256_of(body):
            raise ValueError("payload_sha256 does not match envelope content")


def write_envelope(path: str | Path, env: dict) -> str:
    """Validate then write; returns the recorded payload sha256. Refuses to overwrite."""
    validate_envelope(env)
    p = Path(path)
    if p.exists():
        raise FileExistsError(str(p))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(canonical_bytes(env) + b"\n")
    return env["payload_sha256"]
