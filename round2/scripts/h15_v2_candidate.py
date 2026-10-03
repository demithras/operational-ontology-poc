#!/usr/bin/env python3
"""Pin / check the H15 v2 candidate (src/eoo_openpona2, its domain renders, encoding doc and gaps file).

    .venv/bin/python scripts/h15_v2_candidate.py --write [PATH]   # default protocol/H15_V2_CANDIDATE.json
    .venv/bin/python scripts/h15_v2_candidate.py --check [PATH]   # exit 1 on any mismatch

Hashing is the same as protocol/H15_CANDIDATE.json (sha256 over path NUL bytes NUL, in listed order).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eoo_h15.candidate import v2_files  # noqa: E402
from eoo_h15.evidence import candidate_hash_v2  # noqa: E402

DEFAULT = ROOT / "protocol/H15_V2_CANDIDATE.json"


def build() -> dict:
    files = [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in v2_files()]
    h = hashlib.sha256()
    for e in files:
        h.update(e["path"].encode() + b"\0" + (ROOT / e["path"]).read_bytes() + b"\0")
    return {"purpose": "H15 v2 candidate (OpenPona v2 surface, no coreference labels) pinned before exp-h15-v2-001",
            "prereg": "protocol/H15_V2_PREREG.json",
            "prereg_sha256": hashlib.sha256((ROOT / "protocol/H15_V2_PREREG.json").read_bytes()).hexdigest(),
            "openpona_commit": "97a9b9e8ca8800fda0a22f51ea59fccb6f60f35b", "combined_sha256": h.hexdigest(), "files": files}


def main(argv: list[str]) -> int:
    paths = [a for a in argv if not a.startswith("--")]
    path = Path(paths[0]) if paths else DEFAULT
    if "--write" in argv:
        path.write_text(json.dumps(build(), indent=2) + "\n")
        print(f"wrote {path} combined_sha256={build()['combined_sha256']}")
        return 0
    if "--check" in argv:
        if not path.is_file():
            print(f"FAIL no pin at {path}")
            return 1
        got, want, probs = candidate_hash_v2(path)
        pin = json.loads(path.read_text())
        bad = [e["path"] for e in pin["files"] if hashlib.sha256((ROOT / e["path"]).read_bytes()).hexdigest() != e["sha256"]]
        ok = got == want and not probs and not bad
        print(f"{'OK' if ok else 'FAIL'} v2 candidate {got[:16]}.. pin {want[:16]}.. changed={bad} {probs}")
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
