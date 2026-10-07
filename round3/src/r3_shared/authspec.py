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
    name = "authority-spec-v2.schema.json" if isinstance(spec, dict) and spec.get("spec") == "r3-authority-2" \
        else "authority-spec.schema.json"
    jsonschema.validate(spec, json.loads((root / "schemas" / name).read_text()))
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


def _approver_operations(ops_spec: dict) -> set[str]:
    return {o["approval"]["approver_operation"] for o in ops_spec["operations"] if o.get("approval")}


def validate_strict(spec: dict, ops_spec: dict | None = None, root: Path = ROUND3) -> dict:
    """Strict shared control (ruling R-4), called by BOTH variants on deploy/set_authority and by the harness.

    (spec "r3-authority-2" additionally runs authgraph.validate_graph: capability-edge graph rules, PROT-H24)
    schema + unique principal ids + unique grant ids + no dangling delegation/principal/grant references +
    delegated_by names a known principal + no duplicate delegation pairs; with `ops_spec` additionally: non-round2
    allow grants and delegations may only name operations the ops spec defines (or its approver operations).
    Any violation raises ValueError (schema violations are re-raised as ValueError); returns the spec unchanged.
    """
    try:
        validate_auth_spec(spec, root)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"authority spec violates the schema: {exc.message}") from exc
    gids = [g["id"] for g in spec["grants"]]
    dup = sorted({i for i in gids if gids.count(i) > 1})
    if dup:
        raise ValueError(f"duplicate grant ids: {dup}")
    pids = {p["id"] for p in spec["principals"]}
    for g in spec["grants"]:
        sel = g["principal"]
        if "id" in sel and sel["id"] not in pids:
            raise ValueError(f"grant {g['id']} names unknown principal {sel['id']}")
    pairs = [(d["agent"], d["on_behalf_of"]) for d in spec["delegations"]]
    if len(set(pairs)) != len(pairs):
        raise ValueError("duplicate delegation (agent, on_behalf_of) pairs")
    if ops_spec is not None:
        names = {o["name"] for o in ops_spec["operations"]}
        known = names | _approver_operations(ops_spec)
        for g in spec["grants"]:
            if g["origin"] != "round2" and g["effect"] == "allow" and "*" not in g["operation"] and g["operation"] not in known:
                raise ValueError(f"grant {g['id']}: operation {g['operation']!r} is not in the ops spec")
        for d in spec["delegations"]:
            for o in d["operations"]:
                if o not in names:
                    raise ValueError(f"delegation {d['agent']}->{d['on_behalf_of']}: operation {o!r} is not in the ops spec")
    if spec["spec"] == "r3-authority-2":  # P1d-3: dispatch on `spec`; v1 behaviour above is unchanged
        from .authgraph import validate_graph
        validate_graph(spec, ops_spec)
    return spec
