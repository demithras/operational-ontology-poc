"""Capability edges as version-bound authority objects (PROT-H24 s1-s3, s5).

An `AuthDoc` is the authority state in force: the neutral spec (v1 grants/delegations) plus `capabilities` (edges in
issuance order) and `revoked` (edge ids). Every mutation produces a NEW document, hence a new `authority_version()`:
an edge is bound to the version that issued it (`issued_version`, kept beside the edge by the Core, not in the edge).

Pure functions only (no world, no clock): the Core calls them inside the world transaction with `tx.tick`.
Mutants (frozen names) live at the sites where the real bug would: issuance (`non_attenuating_delegation`), use
(`non_attenuating_delegation`, `expiry_inclusive`) and the decision cache (`stale_authority_cache`, in Core).
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Iterable

from r3_shared.authgraph import V2, edge_path, scope_covers, scope_subset
from r3_shared.authspec import _op_match, _principal_match

MAX_DEPTH = 8
EDGE_KEYS = {"id", "issuer", "child", "parent", "scope", "expires_at", "redelegable", "issued_at"}


def to_v2(doc: dict) -> dict:
    """The same authority as a v2 document (v1 specs gain empty capabilities/revoked and the frozen max depth)."""
    out = copy.deepcopy(doc)
    if out.get("spec") != V2:
        out["spec"] = V2
        out.setdefault("max_delegation_depth", MAX_DEPTH)
        out.setdefault("capabilities", [])
        out.setdefault("revoked", [])
    return out


def edges_of(doc: dict) -> list[dict]:
    return list(doc.get("capabilities", ()))


def revoked_of(doc: dict) -> set[str]:
    return set(doc.get("revoked", ()))


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def schema_ok(e: Any) -> bool:
    if not isinstance(e, dict) or set(e) != EDGE_KEYS:
        return False
    if not (isinstance(e["id"], str) and e["id"]):  # E-9: the v2 edge schema - only `id` has minLength 1
        return False
    if not all(isinstance(e[k], str) for k in ("issuer", "child")) or not (e["parent"] is None or isinstance(e["parent"], str)):
        return False
    if not (e["expires_at"] is None or _is_int(e["expires_at"])) or not _is_int(e["issued_at"]):
        return False
    if not isinstance(e["redelegable"], bool):
        return False
    sc = e["scope"]
    if not isinstance(sc, dict) or set(sc) != {"operations", "resources"}:
        return False
    if not (isinstance(sc["operations"], list) and all(isinstance(o, str) for o in sc["operations"])):
        return False
    if not isinstance(sc["resources"], list):
        return False
    for r in sc["resources"]:
        if not (isinstance(r, dict) and set(r) == {"type", "keys"} and isinstance(r["type"], str)
                and (r["keys"] is None or (isinstance(r["keys"], list) and all(isinstance(k, str) for k in r["keys"])))):
            return False
    return True


def _path_ids(by: dict, eid: str) -> list[dict] | None:
    out, seen, cur = [], set(), eid
    while cur is not None:
        if cur in seen or cur not in by:
            return None
        seen.add(cur)
        out.append(by[cur])
        cur = by[cur]["parent"]
    return out[::-1]


def path_valid(doc: dict, path: list[dict], tick: int, mutants: Iterable[str] = ()) -> bool:
    """Revoked / expired test of PROT-H24 s3 (b)(c) for every edge on the path (strict expiry; mutant: inclusive)."""
    rev = revoked_of(doc)
    incl = "expiry_inclusive" in mutants
    for e in path:
        if e["id"] in rev:
            return False
        x = e["expires_at"]
        if x is not None and not (tick <= x if incl else tick < x):
            return False
    return True


def effective_expiry(doc: dict, edge: dict) -> int | None:
    by = {e["id"]: e for e in edges_of(doc)}
    xs = [e["expires_at"] for e in (_path_ids(by, edge["id"]) or [edge]) if e["expires_at"] is not None]
    return min(xs) if xs else None


def check_issue(doc: dict, edge: Any, subject: str, tick: int, principals: dict, mutants: Iterable[str] = ()) -> tuple:
    """PROT-H24 s2, first failure wins -> (status, reason) or None when the edge may be committed.
    `principals`: {pid: {"id","roles","relations","delegated_by"}} of the authority spec."""
    if not schema_ok(edge):
        return ("INVALID", "schema")
    by = {e["id"]: e for e in edges_of(doc)}
    if edge["id"] in by:
        return ("INVALID", "duplicate_edge")
    if edge["issuer"] != subject:
        return ("DENIED", "not_parent_holder")
    parent = by.get(edge["parent"]) if edge["parent"] is not None else None
    ppath = _path_ids(by, parent["id"]) if parent is not None else []
    if edge["issuer"] == edge["child"] or (ppath and edge["child"] in {e["issuer"] for e in ppath}):
        return ("INVALID", "delegation_cycle")
    for who in (edge["issuer"], edge["child"]):
        p = principals.get(who)
        if p is None:
            return ("INVALID", "unknown_principal")
        if p["delegated_by"] is not None:
            return ("INVALID", "static_delegate")
    if edge["parent"] is not None:
        if parent is None:
            return ("INVALID", "unknown_parent")
        if edge["issuer"] != parent["child"]:
            return ("DENIED", "not_parent_holder")
        if not path_valid(doc, ppath or [parent], tick, mutants):
            return ("DENIED", "parent_invalid")
        if not parent["redelegable"]:
            return ("DENIED", "not_redelegable")
        if len(ppath) + 1 > doc.get("max_delegation_depth", MAX_DEPTH):
            return ("INVALID", "depth_exceeded")
        if "non_attenuating_delegation" not in mutants:  # MUTANT: issuance skips the subset/expiry checks
            if not scope_subset(edge["scope"], parent["scope"]):
                return ("DENIED", "scope_amplification")
            pe = effective_expiry(doc, parent)
            if pe is not None and (edge["expires_at"] is None or edge["expires_at"] > pe):
                return ("DENIED", "expiry_amplification")
    else:
        issuer = principals[edge["issuer"]]
        for op in edge["scope"]["operations"]:
            if not any(g["effect"] == "allow" and g["delegable"] and _op_match(g["operation"], op)
                       and _principal_match(g["principal"], issuer) for g in doc["grants"]):
                return ("DENIED", "scope_amplification")
    if edge["expires_at"] is not None and edge["expires_at"] <= tick:
        return ("INVALID", "already_expired")
    return None


def check_revoke(doc: dict, edge_id: Any, subject: str) -> tuple | None:
    """PROT-H24 s5: (status, reason) refusal, ("OK", "already") for a no-op, or None to apply."""
    by = {e["id"]: e for e in edges_of(doc)}
    if not isinstance(edge_id, str) or edge_id == "":  # E-9: not a non-empty string is schema-INVALID (no envelope)
        return ("INVALID", "schema")
    if edge_id not in by:
        return ("INVALID", "unknown_edge")
    path = _path_ids(by, edge_id) or [by[edge_id]]
    if subject not in {e["issuer"] for e in path}:
        return ("DENIED", "not_revoker")
    if edge_id in revoked_of(doc):
        return ("OK", "already")
    return None


def with_edge(doc: dict, edge: dict) -> dict:
    out = to_v2(doc)
    out["capabilities"] = list(out["capabilities"]) + [copy.deepcopy(edge)]
    return out


def with_revoked(doc: dict, edge_id: str) -> dict:
    out = to_v2(doc)
    out["revoked"] = sorted(set(out["revoked"]) | {edge_id})
    return out


def candidates(doc: dict, subject: str, obo: str) -> list[list[dict]]:
    """Structural candidate paths (root edge .. edge held by `subject`, rooted at `obo`), issuance order. Version-bound:
    the Core caches them per authority version."""
    by = {e["id"]: e for e in edges_of(doc)}
    out = []
    for e in edges_of(doc):
        if e["child"] != subject:
            continue
        p = _path_ids(by, e["id"])
        if p is not None and p[0]["issuer"] == obo:
            out.append(p)
    return out


def find_path(doc: dict, cands: list[list[dict]], op: str, resources: list, tick: int, deny: Callable[[str], bool],
              mutants: Iterable[str] = ()) -> list[str] | None:
    """PROT-H24 s3 (b)-(d),(f) over the candidate paths: the ids of the first VALID path, or None. (a) is built into
    `candidates`; (e) base authority of the root is the Engine's authority gate (it runs after this)."""
    last_only = "non_attenuating_delegation" in mutants  # MUTANT: use evaluates only the last edge's scope
    for p in cands:
        if not path_valid(doc, p, tick, mutants):
            continue
        if not all(scope_covers(e["scope"], op, resources) for e in (p[-1:] if last_only else p)):
            continue
        if any(deny(x) for x in [p[-1]["child"]] + [e["issuer"] for e in p]):
            continue
        return [e["id"] for e in p]
    return None


def chain_issuers(doc: dict, root: str, subject: str) -> set[str]:
    """Q and every issuer on ANY edge path from `root` to `subject` (approval exclusion, PROT-H24 s3), revoked or not."""
    out = {root}
    for p in candidates(doc, subject, root):
        out |= {e["issuer"] for e in p}
    return out
