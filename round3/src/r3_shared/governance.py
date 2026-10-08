"""Governance documents r3-governance-1 (PROT-H25 s1; PROTOCOL-P1e P1e-1). Variant-neutral shared definitions:
loader, strict validator (static rules) and the structural signature. The oracle re-implements the static rules
independently in r3_oracle/constitution.py; a parity test compares accept/reject."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

ROUND3 = Path(__file__).resolve().parents[2]
MODELS = ("hierarchical", "collegial", "polycentric")
EMERGENCY_OP = "emergency:declare"


def load_governance(model: str, domain: str, root: Path = ROUND3) -> dict:
    """Read spec/governance/<model>.<domain>.json (schema-checked; static rules need the specs: validate_governance)."""
    doc = json.loads((root / "spec" / "governance" / f"{model}.{domain}.json").read_text())
    jsonschema.validate(doc, _schema(root))
    return doc


def _schema(root: Path = ROUND3) -> dict:
    return json.loads((root / "schemas" / "governance-spec.schema.json").read_text())


def validate_governance(doc: dict, auth_spec: dict, ops_spec: dict, root: Path = ROUND3) -> dict:
    """Schema + every static rule of PROT-H25 s1; ValueError on any violation (a refused document changes nothing)."""
    try:
        jsonschema.validate(doc, _schema(root))
    except jsonschema.ValidationError as exc:
        raise ValueError(f"governance document violates the schema: {exc.message}") from exc
    principals = {p["id"]: p for p in auth_spec["principals"]}
    bids = [b["id"] for b in doc["bodies"]]
    if len(set(bids)) != len(bids):
        raise ValueError("duplicate body ids")
    mids = [m["id"] for m in doc["matters"]]
    if len(set(mids)) != len(mids):
        raise ValueError("duplicate matter ids")
    known = set(bids)
    for b in doc["bodies"]:
        for m in b["members"]:
            if m not in principals:
                raise ValueError(f"body {b['id']}: member {m!r} is not a principal of the authority spec")
            if principals[m]["delegated_by"] is not None:
                raise ValueError(f"body {b['id']}: member {m!r} is a static delegate")
        r = b["rule"]
        if r["kind"] == "single" and len(b["members"]) != 1:
            raise ValueError(f"body {b['id']}: a single body has exactly one member")
        if r["kind"] == "quorum" and not 1 <= r["k"] <= len(b["members"]):
            raise ValueError(f"body {b['id']}: k {r['k']} outside 1..{len(b['members'])}")
    edges = [tuple(e) for e in doc["superior"]]
    for lo, up in edges:
        if lo not in known or up not in known:
            raise ValueError(f"superior edge {lo}->{up} names an unknown body")
    if _has_cycle(edges):
        raise ValueError("superior relation has a cycle")
    for m in doc["matters"]:
        for c in m["competent"]:
            if c not in known:
                raise ValueError(f"matter {m['id']}: unknown competent body {c}")
        rv = m["review"]
        if rv is not None:
            if rv["by"] not in known:
                raise ValueError(f"matter {m['id']}: unknown reviewing body {rv['by']}")
            if rv["by"] in m["competent"]:
                raise ValueError(f"matter {m['id']}: review by a competent body")
    if len(set(doc["precedence"])) != len(doc["precedence"]):
        raise ValueError("duplicate precedence criteria")
    em = doc["emergency"]
    if em is not None:
        mat = next((m for m in doc["matters"] if m["id"] == em["matter"]), None)
        if mat is None:
            raise ValueError("emergency matter does not exist")
        if not mat["scope"]["operations"] or set(mat["scope"]["operations"]) - {EMERGENCY_OP}:
            raise ValueError(f"emergency matter scope may only contain {EMERGENCY_OP}")
        if em["grantees_from"] not in known:
            raise ValueError("emergency grantees_from names an unknown body")
        names = {o["name"] for o in ops_spec["operations"]} | {
            o["approval"]["approver_operation"] for o in ops_spec["operations"] if o.get("approval")}
        for o in em["ceiling"]["operations"]:
            if o not in names:
                raise ValueError(f"emergency ceiling operation {o!r} is not in the ops spec")
    return doc


def _has_cycle(edges: list[tuple[str, str]]) -> bool:
    up: dict[str, list[str]] = {}
    for lo, hi in edges:
        up.setdefault(lo, []).append(hi)
    state: dict[str, int] = {}

    def visit(n: str) -> bool:
        state[n] = 1
        for h in up.get(n, ()):
            if state.get(h) == 1 or (h not in state and visit(h)):
                return True
        state[n] = 2
        return False
    return any(n not in state and visit(n) for n in list(up))


def _hierarchy(doc: dict) -> str:
    edges = {tuple(e) for e in doc["superior"]}
    if not edges:
        return "none"
    ups: dict[str, int] = {}
    downs: dict[str, int] = {}
    for lo, hi in edges:
        ups[lo] = ups.get(lo, 0) + 1
        downs[hi] = downs.get(hi, 0) + 1
    if max(ups.values()) > 1:
        return "dag"
    return "chain" if max(downs.values()) <= 1 else "tree"


def _overlap(a: dict, b: dict) -> bool:
    if not set(a["operations"]) & set(b["operations"]):
        return False
    for x in a["resources"]:
        for y in b["resources"]:
            if x["type"] == y["type"] and (x["keys"] is None or y["keys"] is None or set(x["keys"]) & set(y["keys"])):
                return True
    return False


def structural_signature(doc: dict) -> dict:
    """Pure structural summary (P1e-1). hierarchy: none (no superior pairs) | chain (every body has <= 1 direct
    superior and <= 1 direct subordinate) | tree (<= 1 superior each) | dag (some body has >= 2 superiors).
    jurisdiction_overlap: two matters share an operation and a resource type with intersecting (or null) key sets."""
    ms = doc["matters"]
    return {
        "decision_rules": sorted({b["rule"]["kind"] for b in doc["bodies"]}),
        "hierarchy": _hierarchy(doc),
        "concurrence": any(m["concurrence"] for m in ms),
        "review": any(m["review"] is not None for m in ms),
        "lapse": any(m["on_absent"] != "await" for m in ms),
        "precedence": tuple(doc["precedence"]),
        "emergency": doc["emergency"] is not None,
        "max_body_size": max(len(b["members"]) for b in doc["bodies"]),
        "jurisdiction_overlap": any(_overlap(ms[i]["scope"], ms[j]["scope"])
                                    for i in range(len(ms)) for j in range(i + 1, len(ms))),
    }


DISTINCT_DIMS = ("decision_rules", "hierarchy", "concurrence", "precedence")


def structurally_distinct(a: dict, b: dict) -> bool:
    """Two models (documents or signatures) are distinct iff their signatures differ in >= 2 of DISTINCT_DIMS."""
    sa = a if "hierarchy" in a and "spec" not in a else structural_signature(a)
    sb = b if "hierarchy" in b and "spec" not in b else structural_signature(b)
    return sum(sa[d] != sb[d] for d in DISTINCT_DIMS) >= 2
