"""The PUBLIC form of a mutating call's result (PROT-H26 s3.6): refusal bodies carry only `reason` (a constant from a fixed
vocabulary: the gate class or the PROT-H23/H24/H25 code), never exception text, values or counts; OK bodies carry ids derived
from the request id (deterministic, s5), never Engine counters.

Mutant error_detail_leak (constructor-activated) returns the raw refusal body plus the failing request's object values.
"""
from __future__ import annotations

from r3_shared.variant import CallResult

_GATE_CODE = {"identity": "token", "request": "request_id", "surface": "authority", "authority": "authority",
              "preconditions": "preconditions", "policy": "policy", "hard_constraints": "constraints",
              "adapter": "dependency_unavailable", "engine": "invalid_request"}


def refusal_code(body: dict) -> str:
    gate, reason = body.get("gate"), body.get("reason", "")
    if gate is None:
        return reason if isinstance(reason, str) else "refused"
    if gate == "inputs":
        return "schema" if reason == "schema" or not reason.startswith("inputs gate refused") else "not_found"
    if gate in ("governance", "delegation"):
        return reason if reason in ("no_valid_path",) or gate == "governance" else "delegation"
    if gate == "approval":
        return "approval_required" if reason == "approval_required" else "approval"
    return _GATE_CODE.get(gate, gate)


def public(res: CallResult, rid=None, leak=None) -> CallResult:
    """`leak`: callable -> dict of the failing request's object values (used ONLY by the error_detail_leak mutant)."""
    if res.status != "OK":
        if leak is not None:
            return CallResult(res.status, {**res.body, "detail": leak()})
        return CallResult(res.status, {"reason": refusal_code(res.body)})
    b = dict(res.body)
    if isinstance(rid, str) and isinstance(b.get("execution"), str) and not b["execution"].startswith("x:"):
        b["execution"] = f"x:{rid}"
        b["effects"] = [f"x:{rid}/e{i}" for i, _ in enumerate(b.get("effects", ()))]
    return CallResult("OK", b)
