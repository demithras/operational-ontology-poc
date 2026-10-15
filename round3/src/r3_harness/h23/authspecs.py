"""The ONE place the H23 harness derives authority specs. Every spec handed to a variant's set_authority is built
here and validated with r3_shared.authspec.validate_strict before it is returned (an invalid spec measures nothing).
Harness-added grants carry origin "neutral-extension" (the schema's only origin for non-round2, non-fix additions)."""
from __future__ import annotations

import copy

from r3_oracle import authority
from r3_shared.authspec import validate_strict

HARNESS_GRANT_ORIGIN = "neutral-extension"


def checked(spec: dict, ops: dict | None = None) -> dict:
    """Validate and return the spec via the shared strict control (R-4): r3_shared.authspec.validate_strict."""
    return validate_strict(spec, ops)


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
