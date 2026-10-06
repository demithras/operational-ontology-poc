"""The ONE place the H23 harness derives authority specs. Every spec handed to a variant's set_authority is built
here and validated with r3_shared.authspec.validate_auth_spec before it is returned (an invalid spec measures nothing).
Harness-added grants carry origin "neutral-extension" (the schema's only origin for non-round2, non-fix additions)."""
from __future__ import annotations

import copy

from r3_oracle import authority
from r3_shared.authspec import validate_auth_spec

HARNESS_GRANT_ORIGIN = "neutral-extension"


def checked(spec: dict) -> dict:
    """Validate and return the spec (raises on schema / consistency violations)."""
    validate_auth_spec(spec)
    return spec


def with_grant(auth: dict, grant: dict) -> dict:
    """Copy of `auth` plus `grant` (origin defaults to neutral-extension; any given origin is kept so the validator
    can reject a bad one), validated."""
    spec = copy.deepcopy(auth)
    spec["grants"].append({"origin": HARNESS_GRANT_ORIGIN, **grant})
    return checked(spec)


def revoked(auth: dict, subject: str, operation: str) -> dict:
    """Copy of `auth` with the subject's grants for the operation removed, validated."""
    return checked(authority.revoke(auth, subject, operation))
