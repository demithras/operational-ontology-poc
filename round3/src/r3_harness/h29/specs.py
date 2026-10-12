"""Frozen inputs of H29: ops/auth/systems per domain (H28 overlay for project, Q2/G4-E4), the authority-version family
(spec/gate5/authority-versions/<domain>/v<n>.json, G5-E1), and the dependency graph."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from r3_harness.h28 import specs as s28

ROUND3 = Path(__file__).resolve().parents[3]
DOMAINS = s28.DOMAINS
GRAPH_PATH = ROUND3 / "spec" / "gate5" / "dependency-graph.json"
FAMILY_DIR = ROUND3 / "spec" / "gate5" / "authority-versions"
_cache: dict = {}


def graph() -> dict:
    if "graph" not in _cache:
        _cache["graph"] = json.loads(GRAPH_PATH.read_text())
    return copy.deepcopy(_cache["graph"])


def load(domain: str):
    """(ops, auth0, systems): auth0 is the version-0 document the AuthorityService starts with (same bytes handed to deploy)."""
    ops, auth, systems = s28.load(domain)
    return ops, auth, systems


def family(domain: str) -> list:
    """[v0, v1, ..., vN]: v0 the frozen version-0 spec, vK each = v0 with exactly one grant removed (narrowing only)."""
    key = ("fam", domain)
    if key not in _cache:
        v0 = load(domain)[1]
        docs = [v0]
        d = FAMILY_DIR / domain
        files = sorted(d.glob("v*.json"), key=lambda p: int(p.stem[1:])) if d.is_dir() else []
        docs += [json.loads(p.read_text()) for p in files]
        _cache[key] = docs
    return copy.deepcopy(_cache[key])


def removed_grant(domain: str, k: int) -> str | None:
    """id of the grant version k removes from version 0 (None for k = 0)."""
    fam = family(domain)
    if k == 0 or k >= len(fam):
        return None
    ids0 = [g["id"] for g in fam[0]["grants"]]
    ids = [g["id"] for g in fam[k]["grants"]]
    gone = [i for i in ids0 if i not in ids]
    return gone[0] if len(gone) == 1 else None


def seed_snapshot(ops: dict) -> dict:
    snap = {"objects": {}, "links": [], "effects": [], "log_head": 0}
    for o in ops["seed"]["objects"]:
        snap["objects"][f"{o['type']}:{o['key']}"] = {"props": dict(o["props"]), "version": 1}
    for lk in ops["seed"]["links"]:
        t = [lk["link_type"], lk["src"], lk["dst"]]
        if t not in snap["links"]:
            snap["links"].append(t)
    return snap


def sysstate_seed(domain: str, ops: dict) -> dict:
    return s28.sysstate_seed(domain, ops)
