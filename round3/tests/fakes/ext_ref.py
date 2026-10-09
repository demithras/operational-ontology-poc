"""Test-support reference of the P1f-6 outcome function (order N, U, D1, D2, D3, S, F, W). FAKES/TESTS ONLY: r3_shared ships no
outcome function (ruling Q4); r3_oracle and each variant implement their own. This copy exists so the fake Deployment is honest
and so protocol tests have an independent statement of the frozen order. Evidence conventions are marked ASSUMPTION where the
frozen text is silent (reported as P1f gaps)."""
from __future__ import annotations

FINAL = ("RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED")


def outcome_state(intent: dict, snap, prev: str, prev_evidence: list, cls: str, obs: str, expiry: int):
    """intent: {operation, target, payload_digest, correlation}; snap: ObsSnapshot or None (observer unavailable = U).
    Returns (state, confidence, evidence)."""
    conf = "low" if obs in ("none", "effects_only") else "full"
    if obs == "none":                                                       # N
        return "UNKNOWN", "low", []
    if snap is None:                                                        # U
        return (prev if prev in FINAL else "UNKNOWN"), conf, (list(prev_evidence) if prev in FINAL else [])   # ASSUMPTION: evidence kept
    M = [r for r in snap.effects if r.correlation == intent["correlation"]]
    A = [r for r in snap.audit if r.correlation == intent["correlation"]] if obs == "full" else []
    ev = sorted({r.seq for r in M} | {r.seq for r in A})                    # ASSUMPTION: seq namespaces of effects/audit merged
    same = lambda r: (r.operation, r.target, r.payload_digest) == (intent["operation"], intent["target"], intent["payload_digest"])  # noqa: E731
    if prev == "DIVERGED":                                                  # D1
        return "DIVERGED", conf, ev
    if any(not same(r) for r in M) or any(not same(r) for r in A):          # D2
        return "DIVERGED", conf, ev
    if cls in ("at_most_once", "exactly_once_required") and len(M) > 1:     # D3
        return "DIVERGED", conf, ev
    if len(M) >= 1:                                                         # S
        return "RECONCILED_SUCCESS", conf, ev
    if snap.complete_through_tick > expiry:                                 # F
        return "RECONCILED_FAILED", conf, ev
    return "PENDING", conf, ev                                              # W
