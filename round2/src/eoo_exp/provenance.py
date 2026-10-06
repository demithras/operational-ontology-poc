"""Protocol pre-flight and evidence-record wrapping (schemas/evidence-record.schema.json)."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path

from .util import ROOT, canon, dirty_paths, head_commit, sha_file, sha_text

PREREG = "protocol/ENGINE_PREREG.json"


def freeze_hash() -> str:
    """Recompute protocol_sha256 exactly as scripts/freeze_protocol.py does, from the files FREEZE.json lists."""
    fz = json.loads((ROOT / "protocol/FREEZE.json").read_text())
    h = hashlib.sha256()
    for f in fz["files"]:
        b = (ROOT / f["path"]).read_bytes()
        h.update(f["path"].encode() + b"\0" + b + b"\0")
    return h.hexdigest()


def prereg_sha() -> str:
    return sha_file(ROOT / PREREG)


def preflight(expected_prereg_sha: str | None = None) -> dict:
    """Refuse (SystemExit) on any frozen-file mismatch. Returns the provenance facts."""
    fz = json.loads((ROOT / "protocol/FREEZE.json").read_text())
    bad = [f["path"] for f in fz["files"] if sha_file(ROOT / f["path"]) != f["sha256"]]
    if bad or freeze_hash() != fz["protocol_sha256"]:
        raise SystemExit(f"REFUSED: FREEZE.json mismatch {bad}")
    pre = json.loads((ROOT / PREREG).read_text())
    if pre["protocol_freeze_sha256"] != fz["protocol_sha256"]:
        raise SystemExit("REFUSED: ENGINE_PREREG.json names a different freeze hash")
    if expected_prereg_sha and prereg_sha() != expected_prereg_sha:
        raise SystemExit("REFUSED: ENGINE_PREREG.json changed")
    return {"protocol_freeze_hash": fz["protocol_sha256"], "engine_prereg_sha256": prereg_sha()}


def environment() -> dict:
    env = {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine()}
    for pkg in ("hypothesis", "jsonschema", "pytest"):
        try:
            env[pkg] = version(pkg)
        except Exception:  # noqa: BLE001
            env[pkg] = None
    return env


def harness_hashes(files: list[Path]) -> dict:
    return {Path(f).resolve().relative_to(ROOT).as_posix(): sha_file(f) for f in files if Path(f).exists()}


def provenance(pre: dict, exp_id: str, hid: str, seed: int, corpus_hash: str, harness_files: list[Path],
               **extra) -> dict:
    dirty = dirty_paths()
    return {"experiment_id": exp_id, "hypothesis_id": hid, "git_commit": head_commit(),
            "protocol_freeze_hash": pre["protocol_freeze_hash"], "engine_prereg_sha256": pre["engine_prereg_sha256"],
            "environment": environment(), "seed": seed, "input_corpus_hash": corpus_hash,
            "harness_dirty": bool(dirty), "harness_dirty_paths": dirty,
            "harness_sha256": harness_hashes(harness_files), **extra}


def wrap(prov: dict, kind: str, payload: dict) -> dict:
    return {**prov, "evidence_kind": kind, "payload_hash": sha_text(canon(payload)), "payload_path": None,
            "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), "payload": payload}


def _default(x):
    if isinstance(x, (set, frozenset)):
        return sorted(x)
    raise TypeError(f"not JSON serialisable: {type(x).__name__}")


def write(dirpath: Path, filename: str, rec: dict) -> None:
    (Path(dirpath) / filename).write_text(json.dumps(rec, indent=1, sort_keys=True, ensure_ascii=True, default=_default) + "\n")
