"""Authority graph v2 pure helpers (PROT-H24 s1; PROTOCOL-P1d P1d-3). Shared definitions, NOT enforcement:
the oracle re-implements these independently in r3_oracle/authority_v2.py and a test compares both."""
from __future__ import annotations

import hashlib
import json
from typing import Iterable

V2 = "r3-authority-2"
V3 = "r3-authority-3"  # v2 + disclosure layer (P1e-6); capability-edge rules identical


def scope_covers(scope: dict, op: str, resources: Iterable[tuple[str, str]]) -> bool:
    """(op, R) is IN scope iff op in operations AND every (T, k) in R is matched by an entry (type T, keys null or k in keys)."""
    if op not in scope["operations"]:
        return False
    return all(any(e["type"] == t and (e["keys"] is None or k in e["keys"]) for e in scope["resources"])
               for t, k in resources)


def scope_subset(child: dict, parent: dict) -> bool:
    """Purely syntactic attenuation: ops(child) <= ops(parent) and every child entry (T, K) has a parent entry
    (T, K') with K' null, or K non-null and K <= K'."""
    if not set(child["operations"]) <= set(parent["operations"]):
        return False
    for e in child["resources"]:
        if not any(p["type"] == e["type"] and (p["keys"] is None or (e["keys"] is not None
                                                                      and set(e["keys"]) <= set(p["keys"])))
                   for p in parent["resources"]):
            return False
    return True


def edge_path(spec: dict, edge_id: str) -> list[dict]:
    """Edges from the root edge down to `edge_id` (inclusive). KeyError on an unknown id; ValueError on a parent cycle."""
    by = {e["id"]: e for e in spec["capabilities"]}
    out, seen, cur = [], set(), edge_id
    while cur is not None:
        if cur in seen:
            raise ValueError(f"parent cycle at edge {cur}")
        seen.add(cur)
        e = by[cur]
        out.append(e)
        cur = e["parent"]
    return out[::-1]


def authority_document(spec: dict) -> dict:
    """v2: capabilities in issuance (list) order, revoked sorted. v1 specs are returned unchanged."""
    if spec.get("spec") not in (V2, V3):
        return spec
    return {**spec, "capabilities": list(spec["capabilities"]), "revoked": sorted(spec["revoked"])}


def authority_digest(spec: dict) -> str:
    doc = authority_document(spec)
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def validate_graph(spec: dict, ops_spec: dict | None = None) -> None:
    """Static v2 checks (after the v1 checks). ValueError on: duplicate edge id, unknown principal, static delegate on an
    edge, missing/later parent, issuer != parent.child, delegation cycle, depth > max, dangling revoked id, scope or expiry
    amplification, operation not in the ops spec. Root-edge delegable-grant coverage is a runtime issuance rule (PROT-H24 2.5)."""
    pdef = {p["id"]: p for p in spec["principals"]}
    maxd = spec["max_delegation_depth"]
    edges = spec["capabilities"]
    seen: dict[str, dict] = {}
    names = None
    if ops_spec is not None:
        names = {o["name"] for o in ops_spec["operations"]} | {
            o["approval"]["approver_operation"] for o in ops_spec["operations"] if o.get("approval")}
    for e in edges:
        eid = e["id"]
        if eid in seen:
            raise ValueError(f"duplicate edge id {eid}")
        for who in (e["issuer"], e["child"]):
            if who not in pdef:
                raise ValueError(f"edge {eid}: unknown principal {who}")
            if pdef[who]["delegated_by"] is not None:
                raise ValueError(f"edge {eid}: static delegate {who} cannot issue or receive edges")
        if e["issuer"] == e["child"]:
            raise ValueError(f"edge {eid}: delegation cycle (issuer == child)")
        parent = None
        if e["parent"] is not None:
            parent = seen.get(e["parent"])
            if parent is None:
                raise ValueError(f"edge {eid}: parent {e['parent']} missing or does not precede it")
            if e["issuer"] != parent["child"]:
                raise ValueError(f"edge {eid}: issuer {e['issuer']} is not the child of parent {parent['id']}")
            path = edge_path({"capabilities": list(seen.values())}, parent["id"])
            if e["child"] in {p["issuer"] for p in path}:
                raise ValueError(f"edge {eid}: delegation cycle (child {e['child']} already on the path)")
            if len(path) + 1 > maxd:
                raise ValueError(f"edge {eid}: depth {len(path) + 1} exceeds max_delegation_depth {maxd}")
            if not scope_subset(e["scope"], parent["scope"]):
                raise ValueError(f"edge {eid}: scope amplification over parent {parent['id']}")
            pe = parent["expires_at"]
            if pe is not None and (e["expires_at"] is None or e["expires_at"] > pe):
                raise ValueError(f"edge {eid}: expiry amplification over parent {parent['id']}")
        elif maxd < 1:
            raise ValueError("max_delegation_depth < 1")
        if names is not None:
            for o in e["scope"]["operations"]:
                if o not in names:
                    raise ValueError(f"edge {eid}: operation {o!r} is not in the ops spec")
        seen[eid] = e
    for r in spec["revoked"]:
        if r not in seen:
            raise ValueError(f"revoked edge {r} does not exist")
