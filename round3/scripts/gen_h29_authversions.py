#!/usr/bin/env python3
"""Deterministically generate spec/gate5/authority-versions/<domain>/v<n>.json (G5-E1): each file = the domain's version-0 authority
spec with EXACTLY ONE allow-grant removed (narrowing only, never widening). Removable grants: allow grants naming one operation of the
domain's ops spec (not '*', not approval:*, not deny grants). usage: gen_h29_authversions.py [--check]  (exit 1 when files differ)"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROUND3 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROUND3 / "src"))
from r3_harness.h28 import specs as s28  # noqa: E402

OUT = ROUND3 / "spec" / "gate5" / "authority-versions"


def build(domain: str) -> list[dict]:
    ops, auth, _ = s28.load(domain)
    names = {o["name"] for o in ops["operations"]}
    docs = []
    for g in auth["grants"]:
        if g["effect"] == "allow" and g["operation"] in names:
            d = copy.deepcopy(auth)
            d["grants"] = [x for x in d["grants"] if x["id"] != g["id"]]
            docs.append(d)
    return docs


def render(doc: dict) -> str:
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    bad = 0
    for dom in s28.DOMAINS:
        docs = build(dom)
        want = {f"v{i + 1}.json": render(d) for i, d in enumerate(docs)}
        d = OUT / dom
        if "--check" in argv:
            have = {p.name: p.read_text() for p in d.glob("v*.json")} if d.is_dir() else {}
            bad += have != want
        else:
            d.mkdir(parents=True, exist_ok=True)
            for old in d.glob("v*.json"):
                old.unlink()
            for n, t in want.items():
                (d / n).write_text(t)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
