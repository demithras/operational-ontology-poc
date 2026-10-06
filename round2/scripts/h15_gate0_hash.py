#!/usr/bin/env python3
"""Gate-0 hash for H15: pins everything H15 is judged AGAINST before any candidate encoding exists.

    python scripts/h15_gate0_hash.py           # (re)write protocol/H15_GATE0.json   -- run it LAST
    python scripts/h15_gate0_hash.py --check   # exit non-zero if any listed file changed, appeared or vanished

Hashed ("files"): every file under src/eoo_ir/ and src/eoo_dsl/ (no __pycache__), domains/*/ir.json,
domains/*/dsl.yaml, protocol/h15_ambiguity_classes.json, ontology/h15_oracle_notes.md. The H15 contract's
pinned candidate-language revision is recorded and compared too. "supporting_files" (provenance tables and the
instantiated DSL ambiguity cases) are hashed and checked as well but are not part of combined_sha256.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "protocol" / "H15_GATE0.json"
CONTRACT = ROOT / "hypotheses" / "h15" / "contract.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:  # OUT patched to a temp path in tests
        return str(p)


def listed() -> tuple[list[Path], list[Path]]:
    def under(d: str) -> list[Path]:
        return [p for p in (ROOT / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]

    files = under("src/eoo_ir") + under("src/eoo_dsl")
    files += sorted((ROOT / "domains").glob("*/ir.json")) + sorted((ROOT / "domains").glob("*/dsl.yaml"))
    files += [ROOT / "protocol/h15_ambiguity_classes.json", ROOT / "ontology/h15_oracle_notes.md"]
    supporting = sorted((ROOT / "domains").glob("*/provenance.md")) + [ROOT / "tests/h15/dsl_ambiguity_cases.jsonl"]
    return sorted(set(files), key=rel), sorted(set(supporting), key=rel)


def snapshot() -> dict:
    files, supporting = listed()
    for p in files + supporting:
        if not p.is_file():
            raise SystemExit(f"required Gate-0 file missing: {rel(p)}")
    pin = json.loads(CONTRACT.read_text())["experiment"]["openpona_pin"]
    entries = [{"path": rel(p), "sha256": sha(p)} for p in files]
    h = hashlib.sha256()
    for e in entries:
        h.update(e["path"].encode() + b"\0" + e["sha256"].encode() + b"\0")
    h.update(json.dumps(pin, sort_keys=True, separators=(",", ":")).encode())
    return {
        "gate": "H15 Gate 0",
        "hash_algorithm": "sha256",
        "files": entries,
        "supporting_files": [{"path": rel(p), "sha256": sha(p)} for p in supporting],
        "openpona_pin": pin,
        "contract_sha256": sha(CONTRACT),
        "combined_sha256": h.hexdigest(),
    }


def main(argv: list[str]) -> int:
    snap = snapshot()
    if "--check" in argv:
        if not OUT.exists():
            print(f"FAIL {rel(OUT)} does not exist")
            return 1
        saved = json.loads(OUT.read_text())
        bad: list[str] = []
        for key in ("files", "supporting_files"):
            old = {e["path"]: e["sha256"] for e in saved.get(key, [])}
            new = {e["path"]: e["sha256"] for e in snap[key]}
            bad += [f"changed {p}" for p in sorted(old.keys() & new.keys()) if old[p] != new[p]]
            bad += [f"added {p}" for p in sorted(new.keys() - old.keys())]
            bad += [f"removed {p}" for p in sorted(old.keys() - new.keys())]
        for key in ("openpona_pin", "contract_sha256", "combined_sha256"):
            if saved.get(key) != snap[key]:
                bad.append(f"{key} differs")
        if bad:
            print("FAIL Gate-0 inputs changed since H15_GATE0.json was written:\n  " + "\n  ".join(bad))
            return 1
        print(f"OK {len(snap['files'])} files + {len(snap['supporting_files'])} supporting files unchanged; combined {snap['combined_sha256']}")
        return 0
    snap = {"written_at": datetime.now(timezone.utc).isoformat(), **snap}
    OUT.write_text(json.dumps(snap, indent=2) + "\n")
    print(f"wrote {rel(OUT)}: {len(snap['files'])} files, combined {snap['combined_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
