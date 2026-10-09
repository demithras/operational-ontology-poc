"""Adapter-side code of the H28 reference fake (FakeHonest): attenuation, submit, outcome function. Clean by construction (the static
audit must report 0 hits here); the mutants live in fake_h28.py behind constructor flags."""
from __future__ import annotations

from r3_shared import extcap
from r3_shared.extadapter import correlation, payload_digest

MAX_ATTEMPTS = 3


def cap_for(root: str, it: dict, tick: int, window: int, broadened: bool = False, fresh: int = 0) -> str:
    if broadened:   # credential_scope_broadened (G4-E5): target and payload binding dropped
        return extcap.attenuate(root, system=it["system"], operation=it["operation"], correlation=correlation(it["request_id"], it["effect_index"]),
                                max_uses=1, not_after_tick=tick + window)
    kw = dict(system=it["system"], operation=it["operation"], target=it["target"], payload_digest=payload_digest(it["payload"]),
              correlation=correlation(it["request_id"], it["effect_index"]), not_after_tick=tick + window + fresh)
    if not fresh:
        kw["max_uses"] = 1 if it["class"] != "idempotent_set" else 3
    return extcap.attenuate(root, **kw)


def outcome(intent, snap, prev, prev_ev, cls, obs, expiry, any_row_success=False, prev_wm=None):
    """P1f-6 (fake's own copy): N, U, D1, D2, D3, S, F, W. any_row_success = divergence_rewritten (no D1/D2/D3)."""
    conf = "low" if obs in ("none", "effects_only") else "full"
    if obs == "none":
        return "UNKNOWN", "low", []
    fin = ("RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED")
    if snap is not None and prev_wm is not None and snap.watermark < prev_wm and prev:      # G4-E16: stale snapshot ignored
        return prev, conf, list(prev_ev)
    if snap is None:
        return (prev, conf, list(prev_ev)) if prev in fin else ("UNKNOWN", conf, [])
    m = [r for r in snap.effects if r.correlation == intent["correlation"]]
    a = [r for r in snap.audit if r.correlation == intent["correlation"]] if obs == "full" else []
    ev = sorted([r.seq for r in m] + [r.seq for r in a])
    same = lambda r: (r.operation, r.target, r.payload_digest) == (intent["operation"], intent["target"], intent["payload_digest"])  # noqa: E731
    if not any_row_success:
        if prev == "DIVERGED" or any(not same(r) for r in m) or any(not same(r) for r in a):
            return "DIVERGED", conf, ev
        if cls in ("at_most_once", "exactly_once_required") and len(m) > 1:
            return "DIVERGED", conf, ev
    if m:
        return "RECONCILED_SUCCESS", conf, ev
    if snap.complete_through_tick > expiry:
        return "RECONCILED_FAILED", conf, ev
    if prev in fin:                                                                         # G4-E16: never back to PENDING
        return prev, conf, list(prev_ev)
    return "PENDING", conf, ev
