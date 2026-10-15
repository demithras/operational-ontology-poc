"""Oracle model of pre-approvals (protocol P1b `Deployment.approve`; auth-spec semantics; ops-spec `approval` block).

An approval authorises ONE commit of the EXACT request (requester, on_behalf_of, operation, canonicalised args).
Valid iff: the approver's token verified; the operation declares an `approval` block; the approver differs from the
requester and lies outside the requester's delegation chain; the approver holds the approval operation
(`approval.approver_operation`) on the request's resources. Pure; imports r3_oracle only.
"""
from __future__ import annotations

import json

from . import authority, ops_model


def canon_args(args) -> str:
    return json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)


def key(requester: str, on_behalf_of: str | None, operation: str, args) -> str:
    return canon_args([requester, on_behalf_of, operation, args])


def approval_operation(ops_spec: dict, operation: str) -> str | None:
    op = ops_model.op_of(ops_spec, operation)
    ap = op.get("approval") if op else None
    return ap["approver_operation"] if ap else None


def validate(ops_spec: dict, auth_spec: dict, approver: str | None, requester: str | None, operation: str, args
             ) -> tuple[bool, str]:
    """(valid, reason). approver/requester None = the token did not verify."""
    if approver is None or requester is None:
        return False, "token does not verify"
    op = ops_model.op_of(ops_spec, operation)
    if op is None:
        return False, "unknown operation"
    aop = approval_operation(ops_spec, operation)
    if aop is None:
        return False, "operation has no approval"
    ok, why, _ = ops_model.validate_args(op, args)
    if not ok:
        return False, f"invalid inputs: {why}"
    if not authority.approver_ok(requester, approver, auth_spec):
        return False, "approver is the requester or inside the requester's delegation chain"
    dec = authority.decide(approver, None, aop, ops_model.resources_of(op, args), auth_spec)
    return (dec.allow, "approver holds the approval operation" if dec.allow else f"approver lacks {aop}: {dec.reason}")
