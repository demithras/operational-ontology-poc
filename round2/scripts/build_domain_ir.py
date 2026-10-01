#!/usr/bin/env python3
"""Regenerate round2/domains/<domain>/{ir.json,dsl.yaml,provenance.md} from the table builders in scripts/domain_build/.

Usage: python scripts/build_domain_ir.py [manufacturing|project|all] [--check]
--check exits non-zero if any committed file differs from what the builders produce.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from domain_build import manufacturing, project  # noqa: E402
from eoo_dsl import compile as dsl_compile, render  # noqa: E402
from eoo_ir import equivalent, validate  # noqa: E402

DOMAINS = {
    "manufacturing": (manufacturing.build, "Manufacturing domain: provenance",
                      "The CURRENT manufacturing product of this repository, expressed as backend-neutral IR. Every resource id below is traced to the source file(s) it comes from; nothing is added that the sources do not have, and every place where the sources were insufficient is listed under *Source gaps and decisions*.",
                      "source file(s)"),
    "project": (project.build, "Project Ontology domain: provenance",
                "The Project Ontology of docs/04_project_ontology_domain.md and docs/05_git_authority.md (plus the clauses of AGENTS.md, ontology/semantic-equivalence.md and src/hdd that they point to), expressed as backend-neutral IR. Every resource id is traced to the doc clause it comes from; choices the docs leave open are listed under *Source gaps and decisions*.",
                "doc clause / source"),
}


def outputs(name: str) -> dict[str, str]:
    fn, title, intro, hdr = DOMAINS[name]
    b = fn()
    ir = b.ir()
    errs = validate(ir)
    assert not errs, [str(e) for e in errs[:10]]
    text = render(ir)
    assert dsl_compile(text) == ir and equivalent(ir, dsl_compile(text)).ok
    return {"ir.json": json.dumps(ir, indent=2, ensure_ascii=False) + "\n", "dsl.yaml": text,
            "provenance.md": b.provenance_md(title, intro, hdr)}


def main(argv: list[str]) -> int:
    check = "--check" in argv
    names = [a for a in argv if not a.startswith("--")] or ["all"]
    names = list(DOMAINS) if names == ["all"] else names
    bad = 0
    for name in names:
        for fname, content in outputs(name).items():
            path = ROOT / "domains" / name / fname
            if check:
                if not path.exists() or path.read_text() != content:
                    print(f"STALE {path.relative_to(ROOT)}")
                    bad += 1
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                print(f"wrote {path.relative_to(ROOT)} ({len(content)} bytes)")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
