"""Delegation table (PROT-H24): pure functions over the authority document.

The document is the neutral v2 authority spec (v1 fields + `capabilities` in issuance order + `revoked`). Nothing here
holds state: the service owns the current document and swaps it inside the commit transaction. Tokens carry identity
only; authority is always re-derived from this table at the commit point (EQUIVALENCE-G2 'conventional').
"""
from __future__ import annotations

import copy
from typing import Callable

from r3_shared.authgraph import V2, edge_path, scope_covers, scope_subset

DEFAULT_MAX_DEPTH = 8
EDGE_KEYS = {"id", "issuer", "child", "parent", "scope", "expires_at", "redelegable", "issued_at"}
Refusal = tuple[str, str]  # (status, reason)


def is_v2(doc: dict) -> bool:
    return doc.get("spec") == V2


def upgraded(doc: dict) -> dict:
    """A v2 copy of `doc` (a v1 spec gains an empty table and the default depth bound)."""
    out = copy.deepcopy(doc)
    if not is_v2(out):
        out.update({"spec": V2, "max_delegation_depth": DEFAULT_MAX_DEPTH, "capabilities": [], "revoked": []})
    return out


def edge_schema_ok(e) -> bool:
    if not isinstance(e, dict) or set(e) != EDGE_KEYS:
        return False
    s = lambda v: isinstance(v, str) and v != ""  # noqa: E731
    i = lambda v: isinstance(v, int) and not isinstance(v, bool)  # noqa: E731
    sc = e["scope"]
    t = lambda v: isinstance(v, str)  # noqa: E731  (schema: issuer/child/parent are plain strings; only id has minLength 1)
    if not (s(e["id"]) and t(e["issuer"]) and t(e["child"]) and (e["parent"] is None or t(e["parent"]))
            and (e["expires_at"] is None or i(e["expires_at"])) and isinstance(e["redelegable"], bool)
            and i(e["issued_at"]) and isinstance(sc, dict) and set(sc) == {"operations", "resources"}):
        return False
    if not isinstance(sc["operations"], list) or not all(isinstance(o, str) for o in sc["operations"]):
        return False
    return isinstance(sc["resources"], list) and all(
        isinstance(r, dict) and set(r) == {"type", "keys"} and isinstance(r["type"], str)
        and (r["keys"] is None or (isinstance(r["keys"], list) and all(isinstance(k, str) for k in r["keys"])))
        for r in sc["resources"])


def by_id(doc: dict) -> dict[str, dict]:
    return {e["id"]: e for e in doc.get("capabilities", [])}


def path_to(doc: dict, edge_id: str) -> list[dict]:
    return edge_path(doc, edge_id)


def path_valid(doc: dict, path: list[dict], tick: int, inclusive_expiry: bool = False) -> bool:
    """Every edge on the path is un-revoked and unexpired at `tick` (strict: usable while tick < expires_at)."""
    rev = set(doc["revoked"])
    for e in path:
        x = e["expires_at"]
        if e["id"] in rev or (x is not None and (tick > x if inclusive_expiry else tick >= x)):
            return False
    return True


def effective_expiry(path: list[dict]) -> int | None:
    xs = [e["expires_at"] for e in path if e["expires_at"] is not None]
    return min(xs) if xs else None


def check_issue(doc: dict, issuer: str, edge: dict, tick: int, known: Callable[[str], bool],
                static_delegate: Callable[[str], bool], root_may_delegate: Callable[[str, list[str]], bool],
                skip_attenuation: bool = False) -> Refusal | None:
    """PROT-H24 s2 steps 2-6 (token and schema are checked by the caller). First failure wins; None = acceptable."""
    caps = by_id(doc)
    if edge["id"] in caps:
        return "INVALID", "duplicate_edge"
    parent = caps.get(edge["parent"]) if edge["parent"] is not None else None
    ppath = path_to(doc, parent["id"]) if parent is not None else []
    if issuer == edge["child"] or (ppath and (edge["child"] in {e["issuer"] for e in ppath})):
        return "INVALID", "delegation_cycle"
    if static_delegate(issuer) or static_delegate(edge["child"]):
        return "INVALID", "static_delegate"
    if not known(edge["child"]):
        return "INVALID", "unknown_principal"
    if edge["parent"] is not None:
        if parent is None:
            return "INVALID", "unknown_parent"
        if parent["child"] != issuer:
            return "DENIED", "not_parent_holder"
        if not path_valid(doc, ppath, tick):
            return "DENIED", "parent_invalid"
        if not parent["redelegable"]:
            return "DENIED", "not_redelegable"
        if len(ppath) + 1 > doc["max_delegation_depth"]:
            return "INVALID", "depth_exceeded"
        if not skip_attenuation:
            if not scope_subset(edge["scope"], parent["scope"]):
                return "DENIED", "scope_amplification"
            pe = effective_expiry(ppath)
            if pe is not None and (edge["expires_at"] is None or edge["expires_at"] > pe):
                return "DENIED", "expiry_amplification"
    elif not skip_attenuation and not root_may_delegate(issuer, edge["scope"]["operations"]):
        return "DENIED", "scope_amplification"
    if edge["expires_at"] is not None and edge["expires_at"] <= tick:
        return "INVALID", "already_expired"
    return None


def add_edge(doc: dict, edge: dict) -> dict:
    out = copy.deepcopy(doc)
    out["capabilities"].append(copy.deepcopy(edge))
    return out


def add_revocation(doc: dict, edge_id: str) -> dict:
    out = copy.deepcopy(doc)
    out["revoked"] = sorted(set(out["revoked"]) | {edge_id})
    return out


def revoker_ok(doc: dict, who: str, edge_id: str) -> bool:
    """The issuer of the edge, or of any edge on its path (an upstream issuer can cut downstream)."""
    return who in {e["issuer"] for e in path_to(doc, edge_id)}


def paths_to(doc: dict, subject: str) -> list[list[dict]]:
    """Every edge path (root .. e) whose last edge's child is `subject`, in issuance order."""
    return [path_to(doc, e["id"]) for e in doc.get("capabilities", []) if e["child"] == subject]


def in_every_scope(path: list[dict], op: str, resources, last_only: bool = False) -> bool:
    return all(scope_covers(e["scope"], op, resources) for e in (path[-1:] if last_only else path))
