"""P1f-6 outcome function, oracle implementation (PROT-H28 R28-5). Independent of every variant and of tests/fakes/ext_ref.py.

Total: any input form has a defined answer (absent -> explicit value, never an exception).
Inputs: the intended effect I (dict), the observer snapshot X (dict form of ObsSnapshot, or None = observer unavailable),
the previous state P, class C, observability O, cap expiry E. Order: N, U, D1, D2, D3, S, F, W.
Evidence follows errata G4-E6: sorted namespaced strings "E:<effects.seq>" / "A:<audit.seq>"; it is informational and
never compared between oracle and variant.
"""
from __future__ import annotations

FINAL = ("RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED")
COUNTED = ("at_most_once", "exactly_once_required")  # G4-E7: D3 applies to both


def _key(r: dict) -> tuple:
    return (r.get("operation"), r.get("target"), r.get("payload_digest"))


def evidence_of(rows_e, rows_a) -> list[str]:
    return sorted([f"E:{r['seq']}" for r in rows_e] + [f"A:{r['seq']}" for r in rows_a])


def outcome_state(intent: dict, snap: dict | None, prev: str | None, prev_evidence: list | None, cls: str, obs: str,
                  expiry: int) -> tuple[str, str, list[str]]:
    """intent: {operation, target, payload_digest, correlation}; snap: {"effects": [...], "audit": [...],
    "complete_through_tick": int} or None (rule U). Returns (state, confidence, evidence)."""
    conf = "low" if obs in ("none", "effects_only") else "full"
    prev_ev = list(prev_evidence or [])
    if obs == "none":                                                                  # N
        return "UNKNOWN", "low", []
    if snap is None:                                                                   # U
        return (prev, conf, prev_ev) if prev in FINAL else ("UNKNOWN", conf, [])
    cor = intent.get("correlation")
    m = [r for r in snap.get("effects", []) if r.get("correlation") == cor]
    a = [r for r in snap.get("audit", []) if r.get("correlation") == cor] if obs == "full" else []
    ev = evidence_of(m, a)
    mine = (intent.get("operation"), intent.get("target"), intent.get("payload_digest"))
    if prev == "DIVERGED":                                                             # D1
        return "DIVERGED", conf, ev
    if any(_key(r) != mine for r in m) or any(_key(r) != mine for r in a):             # D2
        return "DIVERGED", conf, ev
    if cls in COUNTED and len(m) > 1:                                                  # D3
        return "DIVERGED", conf, ev
    if m:                                                                              # S
        return "RECONCILED_SUCCESS", conf, ev
    if isinstance(snap.get("complete_through_tick"), int) and snap["complete_through_tick"] > expiry:  # F
        return "RECONCILED_FAILED", conf, ev
    return "PENDING", conf, ev                                                         # W


def observer_view(ledger: dict, deployment: str, systems: dict, watermark: int, lag: int = 0) -> dict:
    """The snapshot an honest ObservationClient returns at `watermark` with `lag` (P1f-5): rows of this deployment with
    tick <= complete_through_tick, `none` systems omitted, audit only for `full` systems. ledger = extoracle.load_ledger()."""
    ct = max(-1, watermark - lag)
    sysd = systems["systems"]
    vis = {s for s, d in sysd.items() if d["observability"] != "none"}
    full = {s for s, d in sysd.items() if d["observability"] == "full"}
    eff = [r for r in ledger["effects"] if r["deployment"] == deployment and r["tick"] <= ct and r["system"] in vis]
    aud = [r for r in ledger["audit"] if r["deployment"] == deployment and r["tick"] <= ct and r["system"] in full]
    return {"watermark": watermark, "complete_through_tick": ct, "effects": eff, "audit": aud}
