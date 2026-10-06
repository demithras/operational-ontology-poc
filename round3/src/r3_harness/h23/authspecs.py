"""The ONE place the H23 harness derives authority specs. Every spec handed to a variant's set_authority is built
here and validated with r3_shared.authspec.validate_auth_spec before it is returned (an invalid spec measures nothing).
Harness-added grants carry origin "neutral-extension" (the schema's only origin for non-round2, non-fix additions)."""
from __future__ import annotations

import copy

from r3_oracle import authority
from r3_shared.authspec import validate_auth_spec

HARNESS_GRANT_ORIGIN = "neutral-extension"


def _approver_operations(ops: dict) -> set[str]:
    return {o["approval"]["approver_operation"] for o in ops["operations"] if o.get("approval")}


def checked(spec: dict, ops: dict | None = None) -> dict:
    """Validate and return the spec. Beyond the shared schema/consistency validator this rejects what a strict loader
    refuses: duplicate grant ids, duplicate delegations, grants naming an unknown principal id and, when the ops spec
    is given, non-round2 allow grants and delegations naming operations the ops spec does not define."""
    validate_auth_spec(spec)
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
    if ops is not None:
        names = {o["name"] for o in ops["operations"]}
        for g in spec["grants"]:
            if g["origin"] != "round2" and g["effect"] == "allow" and "*" not in g["operation"] and g["operation"] not in names | _approver_operations(ops):
                raise ValueError(f"grant {g['id']}: operation {g['operation']!r} is not in the ops spec")
        for d in spec["delegations"]:
            for o in d["operations"]:
                if o not in names:
                    raise ValueError(f"delegation {d['agent']}->{d['on_behalf_of']}: operation {o!r} is not in the ops spec")
    return spec


def unique_grant_id(auth: dict, base: str) -> str:
    """`base` if unused, else base#2, base#3 ... : the first id no grant of `auth` carries (deterministic)."""
    used = {g["id"] for g in auth["grants"]}
    gid, k = base, 1
    while gid in used:
        k += 1
        gid = f"{base}#{k}"
    return gid


def with_grant(auth: dict, grant: dict, ops: dict | None = None) -> dict:
    """Copy of `auth` plus `grant` (origin defaults to neutral-extension; any given origin is kept so the validator
    can reject a bad one). The id is made unique among the existing grants; validated."""
    spec = copy.deepcopy(auth)
    spec["grants"].append({"origin": HARNESS_GRANT_ORIGIN, **grant, "id": unique_grant_id(auth, grant["id"])})
    return checked(spec, ops)


def revoked(auth: dict, subject: str, operation: str, ops: dict | None = None) -> dict:
    """Copy of `auth` with the subject's grants for the operation removed, validated."""
    return checked(authority.revoke(auth, subject, operation), ops)
