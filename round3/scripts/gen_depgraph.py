#!/usr/bin/env python3
"""Deterministically generate spec/gate5/dependency-graph.json (P1g-4) from the frozen ops specs + systems declarations.
usage: gen_depgraph.py [--check]   (--check: exit 1 when the committed file differs)"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
OUT = ROUND3 / "spec" / "gate5" / "dependency-graph.json"
SOURCES = {"manufacturing": "manufacturing.json", "project": "project.h28.json"}  # project.h28 = base + overlay (H28 ruling Q2)


def build(root: Path = ROUND3) -> dict:
    ops, systems = {}, {}
    for dom, fname in SOURCES.items():
        spec = json.loads((root / "spec" / "ops" / fname).read_text())
        sysd = json.loads((root / "spec" / "external" / f"{dom}.systems.json").read_text())["systems"]
        ops[dom] = {}
        for o in sorted(spec["operations"], key=lambda o: o["name"]):
            outcome = []
            for e in o["effects"]:
                if e["kind"] == "external":
                    outcome.append(f"EXT:{e['adapter']}")
                    if sysd[e["adapter"]]["observability"] != "none":
                        outcome.append("OBS")
            ops[dom][o["name"]] = {"surface": "governed_mutation", "outcome": sorted(set(outcome), key=outcome.index)}
        # per-system outcome-plane nodes (GEN-NULL is generated, observability none -> no OBS)
        systems[dom] = {s: [f"EXT:{s}"] + (["OBS"] if d["observability"] != "none" else []) for s, d in sorted(sysd.items())}
    star = {n: {"surface": "governed_mutation", "outcome": []} for n in ("approve", "delegate", "revoke")}
    return {"version": "r3-depgraph-1", "nodes": ["AUTH", "ANCHOR", "OBS", "EXT:*"],
            "surfaces": {"governed_mutation": {"decision": ["AUTH", "ANCHOR"]}, "read": {"decision": ["AUTH"]},
                         "replay": {"decision": ["ANCHOR"]}, "explain": {"decision": ["ANCHOR"]},
                         "reconcile": {"outcome": ["OBS"]}},
            "operations": {"manufacturing": ops["manufacturing"], "project": ops["project"], "*": star},
            "systems": systems}


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = render(build())
    if "--check" in argv:
        return 0 if OUT.exists() and OUT.read_text() == text else 1
    OUT.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
