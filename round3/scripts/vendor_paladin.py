"""One-shot vendoring of the Round 2 Engine/Toolchain/IR/domain packs into round3/src/paladin (pin 8f9ff26).

Rewrites only import lines; records sha256 of every original and of every vendored file in paladin/VENDORED.json.
Re-running refuses to overwrite (vendored code is edited afterwards; each edit is a documented protection).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

R3 = Path(__file__).resolve().parents[1]
R2 = R3.parent / "round2"
DST = R3 / "src" / "paladin"
PIN = "8f9ff26edfb1dba4528d3c31fe8126bc063b9a11"

# (source relative to round2, destination relative to paladin)
TREES = [("src/eoo_engine", "engine"), ("src/eoo_toolchain", "toolchain")]
FILES = [("src/eoo_ir/validate.py", "ir/validate.py"), ("src/eoo_ir/kinds.py", "ir/kinds.py"),
         ("src/hdd/verdict.py", "domains/_hdd/verdict.py"),
         ("src/hdd/project_lifecycle_reference.py", "domains/_hdd/project_lifecycle_reference.py"),
         ("domains/_support.py", "domains/_support.py"),
         ("domains/manufacturing/ir.json", "domains/manufacturing/ir.json"),
         ("domains/manufacturing/seed.json", "domains/manufacturing/seed.json"),
         ("domains/project/ir.v3.json", "domains/project/ir.v3.json")]
DOMAIN_TREES = [("domains/manufacturing/logic", "domains/manufacturing/logic"),
                ("domains/manufacturing/adapters", "domains/manufacturing/adapters"),
                ("domains/project/logic", "domains/project/logic"),
                ("domains/project/adapters", "domains/project/adapters")]
REWRITES = [(r"\bfrom eoo_ir import\b", "from paladin.ir import"),
            (r"\bfrom eoo_toolchain\.", "from paladin.toolchain."),
            (r"\bfrom eoo_engine\.", "from paladin.engine."),
            (r"\bfrom eoo_engine import\b", "from paladin.engine import"),
            (r"\bfrom domains\._support import\b", "from paladin.domains._support import"),
            (r"\bfrom hdd\.verdict import\b", "from paladin.domains._hdd.verdict import"),
            (r"\bfrom hdd\.project_lifecycle_reference import\b", "from paladin.domains._hdd.project_lifecycle_reference import")]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main() -> int:
    if (DST / "VENDORED.json").exists():
        print("already vendored; refusing to overwrite", file=sys.stderr)
        return 2
    plan = []
    for s, d in TREES + DOMAIN_TREES:
        for f in sorted((R2 / s).rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix in (".py", ".json"):
                plan.append((f, DST / d / f.relative_to(R2 / s)))
    plan += [(R2 / s, DST / d) for s, d in FILES]
    out = {"upstream_pin": PIN, "files": {}}
    for src, dst in plan:
        raw = src.read_bytes()
        text = raw.decode()
        if src.suffix == ".py":
            for pat, rep in REWRITES:
                text = re.sub(pat, rep, text)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text)
        out["files"][str(dst.relative_to(DST))] = {"original": str(src.relative_to(R2.parent)), "original_sha256": sha(raw),
                                                    "vendored_sha256": sha(text.encode())}
    for pkg in ("ir", "domains", "domains/_hdd", "domains/manufacturing", "domains/project"):
        init = DST / pkg / "__init__.py"
        if not init.exists():
            init.write_text('"""Vendored Round 2 package (see paladin/VENDORED.json)."""\n')
    (DST / "VENDORED.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
    print(f"vendored {len(plan)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
