"""Refresh paladin/VENDORED.json: record the CURRENT sha256 of every vendored file and the patch ids applied to it.

`vendored_sha256` is the pristine import-rewritten copy; `current_sha256` is what is in the tree now; a file whose two
hashes differ MUST list its patches (documented with reasons in spec/protections/H23-paladin.md). Run after editing
vendored code; tests/paladin/test_p2a_vendored.py fails on any unrecorded change.
"""
import hashlib
import json
from pathlib import Path

DST = Path(__file__).resolve().parents[1] / "src" / "paladin"
PATCHES = {
    "ir/validate.py": ["V0"], "engine/engine.py": ["V1"], "engine/gates.py": ["V2"], "engine/pipeline.py": ["V3"],
    "domains/manufacturing/logic/facts.py": ["D1", "D5", "D6"], "domains/project/logic/payloads.py": ["D2"],
    "domains/project/logic/freeze.py": ["D3"], "domains/project/logic/derive.py": ["D4", "D7"], "domains/project/logic/facts.py": ["D7"],
}

m = json.loads((DST / "VENDORED.json").read_text())
for rel, rec in m["files"].items():
    rec["current_sha256"] = hashlib.sha256((DST / rel).read_bytes()).hexdigest()
    rec["patches"] = PATCHES.get(rel, [])
(DST / "VENDORED.json").write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
print("files", len(m["files"]), "patched", sum(1 for r in m["files"].values() if r["patches"]))
