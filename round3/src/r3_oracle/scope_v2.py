"""Scope helpers and version digest for the H24 reference authority (PROT-H24 s1). Re-implemented here, NOT imported
from r3_shared.authspec/authgraph; tests/test_h24_oracle.py compares them with the shared helpers on generated scopes.
Pure; no clock, no variant."""
from __future__ import annotations

import hashlib
import json

EDGE_KEYS = frozenset({"id", "issuer", "child", "parent", "scope", "expires_at", "redelegable", "issued_at"})


def covers(scope: dict, op: str, resources) -> bool:
    """(op, R) is IN scope iff op in scope.operations and every (T, k) of R is matched by an entry of scope.resources
    with type T and (keys null or k in keys). No resource inputs: op membership alone."""
    if op not in scope["operations"]:
        return False
    for t, k in resources:
        if not any(e["type"] == t and (e["keys"] is None or k in e["keys"]) for e in scope["resources"]):
            return False
    return True


def subset(child: dict, parent: dict) -> bool:
    """Attenuation: operations(child) <= operations(parent) and every child entry (T, K) has a parent entry (T, K')
    with K' null, or K non-null and K <= K'. Syntactic; a null child key list needs a null parent key list."""
    if not set(child["operations"]) <= set(parent["operations"]):
        return False
    for e in child["resources"]:
        ok = False
        for p in parent["resources"]:
            if p["type"] != e["type"]:
                continue
            if p["keys"] is None or (e["keys"] is not None and set(e["keys"]) <= set(p["keys"])):
                ok = True
                break
        if not ok:
            return False
    return True


def well_formed(edge) -> bool:
    """Schema check of one edge (PROT-H24 s1; additionalProperties false)."""
    if not isinstance(edge, dict) or set(edge) != EDGE_KEYS:
        return False
    i = lambda x: isinstance(x, int) and not isinstance(x, bool)  # noqa: E731
    sc = edge["scope"]
    if not (isinstance(edge["id"], str) and edge["id"] and isinstance(edge["issuer"], str)
            and isinstance(edge["child"], str) and (edge["parent"] is None or isinstance(edge["parent"], str))
            and (edge["expires_at"] is None or i(edge["expires_at"])) and isinstance(edge["redelegable"], bool)
            and i(edge["issued_at"]) and isinstance(sc, dict) and set(sc) == {"operations", "resources"}):
        return False
    if not (isinstance(sc["operations"], list) and all(isinstance(o, str) for o in sc["operations"])
            and isinstance(sc["resources"], list)):
        return False
    return all(isinstance(r, dict) and set(r) == {"type", "keys"} and isinstance(r["type"], str)
               and (r["keys"] is None or (isinstance(r["keys"], list) and all(isinstance(k, str) for k in r["keys"])))
               for r in sc["resources"])


def digest(base: dict, edges: list[dict], revoked) -> str:
    """sha256 of the canonical v2 document: every base field, `capabilities` in issuance order, `revoked` sorted."""
    doc = {**base, "capabilities": list(edges), "revoked": sorted(revoked)}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
