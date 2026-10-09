"""Paladin's OWN implementation of the P1f-6 outcome function (PROT-H28 R28-5, ruling Q4: not shared code).

A pure function of (intent I, observer snapshot X or None = observer unavailable, previous state P, idempotency class C,
observability O, cap expiry E). The adapter reply is NOT an argument: this module never sees one. Rule order (frozen):
N, U, D1, D2, D3, S, F, W.

Evidence (G4-E6 vs schemas/external-outcome.schema.json disagree: namespaced strings vs integers): the shared validator
`r3_shared.outcome.validate_outcome` is the executable form, so evidence is the sorted union of the ledger seqs used.
"""
from __future__ import annotations

FINAL = ("RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED")
AT_MOST = ("at_most_once", "exactly_once_required")


def confidence_of(observability: str) -> str:
    return "low" if observability in ("none", "effects_only") else "full"


def initial(intent: dict) -> dict:
    """The outcome record created when the intent becomes durable (decision committed, nothing observed yet)."""
    o = intent["observability"]
    return {"state": "UNKNOWN" if o == "none" else "PENDING", "confidence": confidence_of(o), "evidence": []}


def _same(row, intent: dict) -> bool:
    return (row.operation, row.target, row.payload_digest) == (intent["operation"], intent["target"], intent["payload_digest"])


def outcome_state(intent: dict, snap, prev: dict, mutants=frozenset()) -> dict:
    """Returns {"state","confidence","evidence"} (evidence: sorted ints)."""
    obs, conf, p = intent["observability"], confidence_of(intent["observability"]), prev["state"]
    if obs == "none":                                                   # N
        return {"state": "UNKNOWN", "confidence": "low", "evidence": []}
    if snap is None:                                                    # U
        return {"state": p if p in FINAL else "UNKNOWN", "confidence": conf, "evidence": list(prev["evidence"])}
    cor = intent["correlation"]
    m = [r for r in snap.effects if r.correlation == cor]
    a = [r for r in snap.audit if r.correlation == cor] if obs == "full" else []
    ev = sorted({r.seq for r in m} | {r.seq for r in a})
    bad = [] if "divergence_rewritten" in mutants else [r for r in (*m, *a) if not _same(r, intent)]
    if p == "DIVERGED":                                                 # D1
        return {"state": "DIVERGED", "confidence": conf, "evidence": sorted(set(prev["evidence"]) | {r.seq for r in bad})}
    if bad:                                                             # D2
        return {"state": "DIVERGED", "confidence": conf, "evidence": sorted({r.seq for r in bad})}
    if intent["idempotency"] in AT_MOST and len(m) > 1 and "divergence_rewritten" not in mutants:   # D3
        return {"state": "DIVERGED", "confidence": conf, "evidence": ev}
    if m:                                                               # S
        return {"state": "RECONCILED_SUCCESS", "confidence": conf, "evidence": ev}
    if snap.complete_through_tick > intent["expiry"]:                   # F
        return {"state": "RECONCILED_FAILED", "confidence": conf, "evidence": ev}
    return {"state": "PENDING", "confidence": conf, "evidence": ev}     # W
