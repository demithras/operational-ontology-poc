"""Shared Gate 3 constitutional FORMS (PROTOCOL-P1e P1e-2/P1e-3; PROT-H25 s3): action schemas, the
`emergency:declare` pseudo-operation, OK bodies, refusal vocabulary and governance-mark payload builders.
Forms only: the decision procedure is each variant's (and the oracle's) own."""
from __future__ import annotations

import hashlib
from typing import Any

from .evidence import canonical_bytes

KINDS = ("propose", "judge", "appeal", "execute", "act", "end")
DECISION_VALUES = ("concur", "dissent", "abstain")
REVIEW_VALUES = ("uphold", "overturn", "abstain")
STAGES = ("decision", "review")
RULES = ("decision", "review", "lapse", "emergency")
# PROT-H25 s3 refusal codes (status class is fixed by the spec text; here only the vocabulary).
REASONS = ("token", "schema", "no_governance", "duplicate_case", "not_governed", "matter_conflict", "no_authority",
           "precedence_unresolved", "unknown_case", "not_eligible", "stage_closed", "already_judged", "not_reviewable",
           "not_decided", "not_party", "already_appealed", "window_closed", "not_requester", "oracle_needed",
           "not_final", "case_denied", "case_required", "scope_amplification", "emergency_too_long", "not_grantee",
           "emergency_inactive", "out_of_emergency_scope", "emergency_expired")

_FIELDS: dict[str, dict[str, type | tuple]] = {
    "propose": {"case": str, "operation": str, "args": dict, "on_behalf_of": (str, type(None))},
    "judge": {"case": str, "stage": str, "value": str, "merit": str},
    "appeal": {"case": str},
    "execute": {"case": str},
    "act": {"emergency": str, "operation": str, "args": dict},
    "end": {"emergency": str},
}

# The pseudo-operation (in no ops spec; writes no canonical object). Shaped like an ops-spec operation so tool_schema
# and the E-9 input checks apply unchanged.
EMERGENCY_DECLARE_OP = {"name": "emergency:declare", "inputs": [
    {"name": "emergency", "type": "string", "required": True},
    {"name": "scope", "type": "json", "required": True},
    {"name": "expires_at", "type": "integer", "required": True},
    {"name": "grantees", "type": "json", "required": True}]}


def check_action(action: Any) -> str | None:
    """None if the action matches its P1e-2 schema (additionalProperties false, all listed keys required);
    otherwise the string 'schema' (the refusal reason, INVALID)."""
    if not isinstance(action, dict) or action.get("kind") not in KINDS:
        return "schema"
    f = _FIELDS[action["kind"]]
    if set(action) != {"kind", *f}:
        return "schema"
    for k, t in f.items():
        v = action[k]
        if isinstance(v, bool) or not isinstance(v, t):
            return "schema"
    if action["kind"] == "judge":
        allowed = DECISION_VALUES if action["stage"] == "decision" else REVIEW_VALUES if action["stage"] == "review" else ()
        if action["value"] not in allowed:
            return "schema"
    return None


def ok_body(kind: str, **kw: Any) -> dict:
    """Frozen OK bodies: propose {case,bodies sorted}, judge {case,stage}, appeal {case}, end {emergency}.
    (execute/act return the operation's normal OK body - not built here.)"""
    if kind == "propose":
        return {"case": kw["case"], "bodies": sorted(kw["bodies"])}
    if kind == "judge":
        return {"case": kw["case"], "stage": kw["stage"]}
    if kind == "appeal":
        return {"case": kw["case"]}
    if kind == "end":
        return {"emergency": kw["emergency"]}
    raise ValueError(f"no frozen OK body for {kind!r}")


def refusal_body(reason: str) -> dict:
    if reason not in REASONS:
        raise ValueError(f"unknown refusal code {reason!r}")
    return {"reason": reason}


def digest(x: Any) -> str:
    return hashlib.sha256(canonical_bytes(x)).hexdigest()


def args_digest(args: dict) -> str:
    return digest(args)


def merit_digest(merit: str) -> str:
    return digest(merit)


MARK_KEYS = {
    "propose": {"op", "case", "requester", "on_behalf_of", "operation", "args_digest", "bodies"},
    "judge": {"op", "case", "stage", "judge", "value", "merit_digest"},
    "appeal": {"op", "case", "by"},
    "execute": {"op", "case", "outcome", "rule", "basis"},
    "act": {"op", "emergency", "operation", "args_digest"},
    "end": {"op", "emergency"},
    "set_governance": {"op", "version"},
}


def governance_mark(op: str, **kw: Any) -> dict:
    """Build a P1e-3 payload (every key present, no extras). `bodies` is sorted; derived digests are computed here:
    pass args= / merit= (raw) and get args_digest / merit_digest; set_governance takes doc= -> version."""
    if op not in MARK_KEYS:
        raise ValueError(f"unknown governance mark op {op!r}")
    p: dict[str, Any] = {"op": op}
    if op == "propose":
        p |= {"case": kw["case"], "requester": kw["requester"], "on_behalf_of": kw["on_behalf_of"],
              "operation": kw["operation"], "args_digest": args_digest(kw["args"]), "bodies": sorted(kw["bodies"])}
    elif op == "judge":
        p |= {"case": kw["case"], "stage": kw["stage"], "judge": kw["judge"], "value": kw["value"],
              "merit_digest": merit_digest(kw["merit"])}
    elif op == "appeal":
        p |= {"case": kw["case"], "by": kw["by"]}
    elif op == "execute":
        p |= {"case": kw["case"], "outcome": "ALLOW", "rule": kw["rule"], "basis": list(kw["basis"])}
    elif op == "act":
        p |= {"emergency": kw["emergency"], "operation": kw["operation"], "args_digest": args_digest(kw["args"])}
    elif op == "end":
        p |= {"emergency": kw["emergency"]}
    else:
        p |= {"version": digest(kw["doc"])}
    check_mark(p)
    return p


def check_mark(p: Any) -> None:
    if not isinstance(p, dict) or p.get("op") not in MARK_KEYS:
        raise ValueError("governance mark: unknown op")
    if set(p) != MARK_KEYS[p["op"]]:
        raise ValueError(f"governance mark {p['op']}: keys {sorted(p)} != {sorted(MARK_KEYS[p['op']])}")
    if p["op"] == "execute" and (p["outcome"] != "ALLOW" or p["rule"] not in ("decision", "review", "lapse")):
        raise ValueError("execute mark: outcome ALLOW and rule decision|review|lapse")
    if p["op"] == "judge" and p["stage"] not in STAGES:
        raise ValueError("judge mark: stage")
