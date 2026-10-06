"""Frozen-contract digest = the algorithm of scripts/freeze_protocol.py (sha256 over ``path \\0 bytes \\0`` per file),
plus the read-only blob reader (``git show``) the domain logic uses to see committed bytes."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Callable

from paladin.domains._support import canonical_json

ROUND2 = Path(__file__).resolve().parents[3]
BlobReader = Callable[[str], bytes]


def freeze_digest(entries: list[tuple[str, bytes]]) -> str:
    """Byte-for-byte what scripts/freeze_protocol.py hashes: ``rel.encode() + 0 + bytes + 0`` for each file."""
    h = hashlib.sha256()
    for rel, data in entries:
        h.update(rel.encode() + b"\0" + data + b"\0")
    return h.hexdigest()


def git_blob_reader(ref: str = "HEAD", root: Path = ROUND2) -> BlobReader:
    """Read a round2-relative path as committed at ``ref`` (never the working tree; never writes)."""
    def read(path: str) -> bytes:
        res = subprocess.run(["git", "-C", str(root), "show", f"{ref}:./{path}"], capture_output=True, timeout=60)
        if res.returncode != 0:
            raise FileNotFoundError(f"{ref}:{path}: {res.stderr.decode(errors='replace').strip()}")
        return res.stdout
    return read


def frozen_paths(experiment_props: dict) -> list[str]:
    """Repo paths named by evidence_schema_ref then evaluator_ref: comma-separated lists, ``:symbol`` suffix and
    ``#fragment`` dropped. Order is preserved (it is part of the hash)."""
    paths: list[str] = []
    for ref in (experiment_props["evidence_schema_ref"], experiment_props["evaluator_ref"]):
        for part in str(ref).split(","):
            part = part.strip().split("#")[0].split(":")[0]
            if part:
                paths.append(part)
    return paths


def compute_freeze_hash(view, eid, reader: BlobReader) -> str:
    """sha256 over the frozen files of the experiment, then one pseudo-file ``threshold:<id>`` (canonical JSON of the
    value) for each threshold its metrics are governed by. An experiment with no thresholds hashes exactly like
    scripts/freeze_protocol.py would hash those files."""
    e = view.get("Experiment", eid)
    if e is None:
        raise KeyError(f"unknown experiment {eid!r}")
    entries = [(p, reader(p)) for p in frozen_paths(e["props"])]
    seen = []
    for m in view.follow("MEASURES", "Experiment", eid, "out"):
        for t in view.follow("GOVERNED_BY", "Metric", m["key"], "out"):
            if t["key"] not in seen:
                seen.append(t["key"])
                entries.append((f"threshold:{t['key']}", canonical_json(t["props"]["value"]).encode()))
    return freeze_digest(entries)
