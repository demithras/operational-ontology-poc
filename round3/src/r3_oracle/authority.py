"""Pure effective-authority oracle. Implements the frozen rule of spec/protections/PROT-H23.md over the neutral
authority fixture (spec/authority/<domain>.json). Imports nothing from any variant.

decide(subject, on_behalf_of, operation, resources, auth_spec) -> Decision(allow, reason)
`resources` = the (type, key) pairs of the request's resource-typed inputs.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.allow


ALLOW = "ALLOW"
DENY = "DENY"


def _op_match(pattern: str, op: str) -> bool:
    return pattern == op or pattern == "*" or (pattern.endswith(":*") and op.startswith(pattern[:-1]))


def _principal(spec: dict, pid: str) -> dict | None:
    return next((p for p in spec["principals"] if p["id"] == pid), None)


def _sel_principal(sel: dict, p: dict, resources) -> bool:
    if sel.get("any"):
        return True
    if "role" in sel:
        return sel["role"] in p["roles"]
    if "id" in sel:
        return sel["id"] == p["id"]
    if "relation" in sel:
        of_type = [r for r in resources if r[0] == sel["on_type"]]
        held = {(r["type"], r["key"]) for r in p["relations"] if r["relation"] == sel["relation"]}
        return bool(of_type) and all(tuple(r) in held for r in of_type)
    return False


def _sel_resource(sel: dict, resources) -> bool:
    if sel.get("any"):
        return True
    if "type" in sel and "state" not in sel:
        return any(r[0] == sel["type"] for r in resources)
    return False  # state-conditioned selectors apply to pseudo-operations only


def _matching(spec: dict, effect: str, p: dict, op: str, resources) -> list[dict]:
    return [g for g in spec["grants"]
            if g["effect"] == effect and _op_match(g["operation"], op)
            and _sel_principal(g["principal"], p, resources) and _sel_resource(g["resource"], resources)]


def _chain(spec: dict, pid: str) -> list[dict]:
    out, seen = [], set()
    while pid is not None and pid not in seen:
        seen.add(pid)
        p = _principal(spec, pid)
        if p is None:
            break
        out.append(p)
        pid = p["delegated_by"]
    return out


def _self_allowed(spec: dict, pid: str, op: str, resources) -> tuple[bool, str, list[dict]]:
    p = _principal(spec, pid)
    if p is None:
        return False, f"unknown principal {pid}", []
    if _matching(spec, "deny", p, op, resources):
        return False, f"deny grant matches {pid}", []
    allows = _matching(spec, "allow", p, op, resources)
    if not allows:
        return False, f"no allow grant matches {pid}", []
    return True, "allow grant matches", allows


def decide(subject: str, on_behalf_of: str | None, operation: str, resources, auth_spec: dict) -> Decision:
    resources = [tuple(r) for r in resources]
    ok, why, allows = _self_allowed(auth_spec, subject, operation, resources)
    if on_behalf_of is None:
        return Decision(ok, why)
    if not ok:
        return Decision(False, f"agent itself not allowed: {why}")
    if not any(d["agent"] == subject and d["on_behalf_of"] == on_behalf_of and operation in d["operations"]
               for d in auth_spec["delegations"]):
        return Decision(False, "no delegation entry for this agent/principal/operation")
    if not any(g["delegable"] for g in allows):
        return Decision(False, "matching allow grant is not delegable")
    p_ok, p_why, _ = _self_allowed(auth_spec, on_behalf_of, operation, resources)
    if not p_ok:
        return Decision(False, f"delegator not allowed: {p_why}")
    for who in _chain(auth_spec, subject):
        if _matching(auth_spec, "deny", who, operation, resources):
            return Decision(False, f"deny grant matches delegation chain member {who['id']}")
    return Decision(True, "delegated and delegator allowed")


def actor_for_rules(subject: str, on_behalf_of: str | None, auth_spec: dict) -> str:
    """Principal whose relations business rules (`actor_holds`) consult: the delegator when acting on behalf of."""
    return on_behalf_of if on_behalf_of is not None else subject


def relations_of(auth_spec: dict, pid: str) -> set[tuple[str, str, str]]:
    p = _principal(auth_spec, pid)
    return set() if p is None else {(r["type"], r["key"], r["relation"]) for r in p["relations"]}


def approver_ok(requester: str, approver: str, auth_spec: dict) -> bool:
    """Approver differs from the requester and lies outside the requester's delegation chain."""
    return approver != requester and approver not in {p["id"] for p in _chain(auth_spec, requester)}


def could_ever_allow(subject: str, operation: str, auth_spec: dict) -> bool:
    """Upper bound for the surface audit: is there ANY resource binding for which decide() could allow the subject
    (as itself, or on behalf of a delegator that could itself be allowed)?"""
    p = _principal(auth_spec, subject)
    if p is None:
        return False

    def own(pid: str) -> list[dict]:
        q = _principal(auth_spec, pid)
        if q is None:
            return []
        out = []
        for g in auth_spec["grants"]:
            if g["effect"] != "allow" or not _op_match(g["operation"], operation):
                continue
            s = g["principal"]
            if s.get("any") or ("role" in s and s["role"] in q["roles"]) or ("id" in s and s["id"] == q["id"]) \
                    or ("relation" in s and any(r["relation"] == s["relation"] and r["type"] == s["on_type"]
                                                for r in q["relations"])):
                out.append(g)
        return out

    # delegation needs the agent's OWN delegable allow grant, so it never widens the upper bound.
    return bool(own(subject))


def revoke(auth_spec: dict, subject: str, operation: str) -> dict:
    """Copy of auth_spec with every allow grant that can match `subject` for `operation` removed, and the subject's
    delegation entries for it dropped (used by the replay-after-revocation attack)."""
    import copy
    new = copy.deepcopy(auth_spec)
    p = _principal(new, subject)
    keep = []
    for g in new["grants"]:
        s = g["principal"]
        hit = g["effect"] == "allow" and _op_match(g["operation"], operation) and p is not None and (
            s.get("any") or ("role" in s and s["role"] in p["roles"]) or ("id" in s and s["id"] == p["id"])
            or ("relation" in s and any(r["relation"] == s["relation"] and r["type"] == s["on_type"]
                                        for r in p["relations"])))
        if not hit:
            keep.append(g)
    new["grants"] = keep
    new["delegations"] = [d for d in new["delegations"] if not (d["agent"] == subject and operation in d["operations"])]
    return new
