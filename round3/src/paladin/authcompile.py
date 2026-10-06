"""Compile the NEUTRAL authority spec (spec/authority/<domain>.json) into the Engine's configuration.

No per-domain privilege code: the compiler is a pure function of (IR package, authority spec). It
 * replaces the IR's `authority_rules` with one Engine rule per allow/deny grant that can match an `action:<op>` or an
   `approval:*` capability (selector translation below), and rewrites every action's `authority_refs`;
 * produces the Engine `Principal` objects (static principals have delegated_by=None; delegated requests are built per
   request in `deployment.py` from the spec's `delegations`).
Selector translation: {relation,on_type} -> "<T>#<rel>"; {role} -> "role:r"; {id} -> "principal:p"; {any} -> "*";
resource {type:T} -> "T:*"; {any} -> "*". Deny grants on pseudo-operations (`write:*`, `update:*`) never match an
`action:*` capability; they stay enforced structurally (the only Engine write path is the governed action pipeline
with a WriteGrant, see H23-paladin.md) and are skipped here rather than compiled into dead rules.
"""
from __future__ import annotations

import copy

from paladin.engine import Principal


def _psel(sel: dict) -> str:
    if sel.get("any"):
        return "*"
    if "relation" in sel:
        return f"{sel['on_type']}#{sel['relation']}"
    if "role" in sel:
        return f"role:{sel['role']}"
    if "id" in sel:
        return f"principal:{sel['id']}"
    raise ValueError(f"unsupported principal selector {sel}")


def _rsel(sel: dict) -> str:
    if sel.get("any"):
        return "*"
    if "type" in sel and "state" not in sel:
        return f"{sel['type']}:*"
    raise ValueError(f"unsupported resource selector {sel}")


def _cap_matches(pattern: str, cap: str) -> bool:
    return pattern == cap or pattern == "*" or (pattern.endswith(":*") and cap.startswith(pattern[:-1]))


def _capability(op: str) -> str:
    """Spec operation pattern -> Engine capability string."""
    if op == "*" or op.startswith(("approval:", "write:", "update:")) or op.endswith(":*"):
        return op
    return f"action:{op}"


def compile_ir(ir: dict, auth: dict, ops: dict) -> dict:
    out = copy.deepcopy(ir)
    rules, by_op = [], {}
    for g in auth["grants"]:
        op = g["operation"]
        if op.startswith(("write:", "update:")) or g["resource"].get("state"):
            continue  # structural / state-conditioned deny: see module docstring
        rid = g["id"]
        rules.append({"id": rid, "principal_selector": _psel(g["principal"]), "capability": _capability(op),
                      "resource_selector": _rsel(g["resource"]), "effect": g["effect"],
                      "delegation_allowed": bool(g["delegable"])})
    out["authority_rules"] = rules
    approvals = {o["name"]: (o.get("approval") or {}).get("approver_operation") for o in ops["operations"]}
    for a in out["actions"]:
        caps = [f"action:{a['id']}"] + ([approvals[a["id"]]] if approvals.get(a["id"]) else [])
        a["authority_refs"] = [f"auth:{r['id']}" for r in rules if any(_cap_matches(r["capability"], c) for c in caps)]
    return out


def principals(auth: dict) -> dict[str, Principal]:
    """Static principals (no delegation): one Engine Principal per spec principal id."""
    return {p["id"]: Principal(p["id"], frozenset(p["roles"]),
                               frozenset((r["type"], r["key"], r["relation"]) for r in p["relations"]))
            for p in auth["principals"]}


def delegation_table(auth: dict) -> dict[tuple[str, str], frozenset]:
    return {(d["agent"], d["on_behalf_of"]): frozenset(d["operations"]) for d in auth["delegations"]}
