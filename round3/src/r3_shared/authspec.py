"""Loader/validator and a static reference for the neutral authority fixture (spec/authority/<domain>.json).

`allowed_operations` is a *static* upper bound (ignores per-request resource binding): the set of operation names a
principal may be granted at all, honouring deny-overrides and delegation (delegable grant AND delegator allowed).
It is the shared definition both variants configure themselves from and the oracle reads; it is not enforcement.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

ROUND3 = Path(__file__).resolve().parents[2]


def load_auth_spec(domain: str, root: Path = ROUND3) -> dict:
    spec = json.loads((root / "spec" / "authority" / f"{domain}.json").read_text())
    validate_auth_spec(spec, root)
    return spec


def validate_auth_spec(spec: dict, root: Path = ROUND3) -> None:
    jsonschema.validate(spec, json.loads((root / "schemas" / "authority-spec.schema.json").read_text()))
    ids = [p["id"] for p in spec["principals"]]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate principal ids")
    for p in spec["principals"]:
        if p["delegated_by"] is not None and p["delegated_by"] not in ids:
            raise ValueError(f"{p['id']}: delegated_by {p['delegated_by']} is not a principal")
    for d in spec["delegations"]:
        if d["agent"] not in ids or d["on_behalf_of"] not in ids:
            raise ValueError(f"delegation {d} names an unknown principal")


def _op_match(pattern: str, op: str) -> bool:
    return pattern == op or pattern == "*" or (pattern.endswith(":*") and op.startswith(pattern[:-1]))


def _principal_match(sel: dict, p: dict) -> bool:
    if sel.get("any"):
        return True
    if "role" in sel:
        return sel["role"] in p["roles"]
    if "id" in sel:
        return sel["id"] == p["id"]
    if "relation" in sel:  # static view: holds the relation on at least one resource of that type
        return any(r["type"] == sel["on_type"] and r["relation"] == sel["relation"] for r in p["relations"])
    return False


def _chain(spec: dict, pid: str) -> list[dict]:
    by, out, seen = {p["id"]: p for p in spec["principals"]}, [], set()
    while pid is not None and pid not in seen:
        seen.add(pid)
        out.append(by[pid])
        pid = by[pid]["delegated_by"]
    return out


def allowed_operations(spec: dict, pid: str, operations: list[str], _depth: int = 0) -> set[str]:
    """Operations (from `operations`) the principal may be granted. Deny on the principal or any delegator wins."""
    if _depth > 16:
        return set()
    chain = _chain(spec, pid)
    p, allowed = chain[0], set()
    for op in operations:
        if any(g["effect"] == "deny" and _op_match(g["operation"], op) and _principal_match(g["principal"], who)
               for who in chain for g in spec["grants"]):
            continue
        for g in spec["grants"]:
            if g["effect"] != "allow" or not _op_match(g["operation"], op) or not _principal_match(g["principal"], p):
                continue
            if p["delegated_by"] is None:
                allowed.add(op)
            elif g["delegable"] and op in allowed_operations(spec, p["delegated_by"], [op], _depth + 1):
                allowed.add(op)
    return allowed
