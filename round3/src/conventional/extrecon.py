"""Reconciler: outcome state machine for external effects (PROT-H28 R28-4..R28-6, R28-9, R28-10; P1f-6).

Adapter-side code (ADAPTER_MODULES). The ONLY evidence is the observer snapshot (ObservationClient); an adapter reply is
never an argument of `outcome_state`. Independent implementation of the P1f-6 order N, U, D1, D2, D3, S, F, W
(ruling Q4: not shared with r3_oracle or any other variant). Observability and idempotency classes are read from the
frozen system declarations (data), never hard-coded per system name (R28-10).
"""
from __future__ import annotations

from r3_shared import outcome as oc
import json

from r3_shared.extadapter import payload_digest
from r3_shared.extobs import EffRow, ObsSnapshot, ObserverUnavailable

KEEP_CLASSES = ("at_most_once", "exactly_once_required")  # D3 applies to both (G4-E7)


def confidence_for(observability: str) -> str:
    return "low" if observability in oc.LOW_CONFIDENCE_OBSERVABILITY else "full"


def outcome_state(intent: dict, snap, prev: str, cls: str, observability: str, expiry: int, prev_ev=(), compare=True) -> tuple[str, str, list]:
    """intent: {operation, target, payload_digest, correlation}; snap: ObsSnapshot or None (observer unavailable = rule U).
    Returns (state, confidence, evidence) where evidence is the sorted DISTINCT ints of P1f-6 / G4-E20."""
    conf = confidence_for(observability)
    if observability == "none":                                              # N: stop rule, for ever
        return "UNKNOWN", "low", []
    if snap is None:                                                         # U
        final = prev in oc.FINAL_STATES  # G4-E7: rule U keeps the previous state's evidence
        return (prev if final else "UNKNOWN"), conf, (list(prev_ev) if final else [])
    key = (intent["operation"], intent["target"], intent["payload_digest"])
    applied = [r for r in snap.effects if r.correlation == intent["correlation"]]
    audited = [r for r in snap.audit if r.correlation == intent["correlation"]] if observability == "full" else []
    ev = _ev(applied, audited)
    mismatch = [r for r in (*applied, *audited) if (r.operation, r.target, r.payload_digest) != key] if compare else []
    if prev == "DIVERGED" or mismatch:                                       # D1, D2 (evidence: the conflicting rows)
        return "DIVERGED", conf, (_ev([r for r in mismatch if r in applied], [r for r in mismatch if r not in applied]) or ev)
    if cls in KEEP_CLASSES and len(applied) > 1:                             # D3
        return "DIVERGED", conf, ev
    if len(applied) >= 1:                                                    # S
        return "RECONCILED_SUCCESS", conf, ev
    if snap.complete_through_tick > expiry:                                  # F
        return "RECONCILED_FAILED", conf, ev
    return "PENDING", conf, ev                                               # W


def _ev(applied, audited) -> list:
    """G4-E19/E20: effects.seq of the effect rows plus audit.seq of the audit rows; sorted, DISTINCT, positive ints."""
    return sorted({int(r.seq) for r in (*applied, *audited)})


def initial_state(observability: str) -> tuple[str, str]:
    """State written in the commit transaction: PENDING (full/effects_only); a `none` system is UNKNOWN/low from the start."""
    if observability == "none":
        return "UNKNOWN", "low"
    return "PENDING", confidence_for(observability)


def public_evidence(evidence: list) -> list:
    """Public OUTCOME.evidence (G4-E20): the stored sorted distinct ints, unchanged."""
    return sorted({int(x) for x in evidence})


def read_snapshot(observer, watermark: int):
    """Observer snapshot or None when the observer is unavailable (rule U)."""
    try:
        return observer.read(watermark=watermark)
    except ObserverUnavailable:
        return None


def next_state(prev: str, new: str, new_conf: str, new_ev: list, prev_conf: str, prev_ev: list):
    """R28-6 monotone safety: RECONCILED_* moves only to DIVERGED. A transition the table forbids is refused (state kept)."""
    if oc.allowed_transition(prev, new):
        return new, new_conf, new_ev
    return prev, prev_conf, prev_ev


def _adapter_snapshot(it: dict, watermark: int) -> ObsSnapshot:
    """BUG (observation_coupled): a snapshot fabricated from the adapter's own reply instead of the observer's ledger."""
    rows = []
    if it["reply"] == "OK":
        rows = [EffRow(0, it["commit_tick"], it["system"], it["operation"], it["target"],
                       payload_digest(json.loads(it["payload_json"])),
                       "", f"{it['request_id']}#{it['effect_index']}", "adapter")]
    return ObsSnapshot(watermark, rows, [], watermark)


def reconcile(h, intents: list[dict], observer, watermark: int, mutants=frozenset(), guard=None) -> None:
    """Update the outcome records of `intents` (one request) from ONE observer snapshot (R28-5). Durable, idempotent."""
    coupled = "observation_coupled" in mutants
    snap = None if coupled else read_snapshot(observer, watermark)
    if guard is not None and not coupled:   # G5: the OBS breaker follows what the observer answered (descriptive status only)
        guard.up("OBS") if snap is not None else guard.down("OBS")
    for it in intents:
        cur = h._con.execute("SELECT state, confidence, evidence_json, wm FROM conv_outcome WHERE request_id=? AND effect_index=?",
                             (it["request_id"], it["effect_index"])).fetchone()
        prev, prev_conf, prev_ev = cur[0], cur[1], json.loads(cur[2])
        if watermark < cur[3]:  # G4-E16: a snapshot older than one already applied is ignored (state + evidence stay)
            continue
        use = _adapter_snapshot(it, watermark) if coupled else snap
        intent = {"operation": it["operation"], "target": it["target"], "correlation": f"{it['request_id']}#{it['effect_index']}",
                  "payload_digest": payload_digest(json.loads(it["payload_json"]))}
        new, conf, ev = outcome_state(intent, use, prev, it["cls"], it["observability"], it["expiry"], prev_ev,
                                      compare="divergence_rewritten" not in mutants)
        new, conf, ev = next_state(prev, new, conf, ev, prev_conf, prev_ev)
        h._con.execute("UPDATE conv_outcome SET state=?, confidence=?, evidence_json=?, wm=? WHERE request_id=? AND effect_index=?",
                       (new, conf, json.dumps(ev), watermark if snap is not None or coupled else cur[3],
                        it["request_id"], it["effect_index"]))
