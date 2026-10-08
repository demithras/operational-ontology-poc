"""State-checkable ops-spec invariants evaluated on a snapshot (G3-E28: generated worlds satisfy every ops-spec invariant).
Every invariant id of spec/ops/*.json is either checked here (STATE) or named in NON_STATE with the reason it is not a
property of one snapshot (history, transition, commit-time or store-level). tests/test_h26_g3_fix5.py enforces this
partition so a new invariant cannot be silently skipped. Pure; no candidate code."""
from __future__ import annotations

def _objs(s, t):
    return [(r, o["props"]) for r, o in s["objects"].items() if r.split(":", 1)[0] == t]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _bad_lots(s, pred):
    return [r for r, p in _objs(s, "InventoryLot") if not pred(p.get("onHand"), p.get("reserved"))]


def _ok2(f):
    return lambda a, b: _num(a) is not None and _num(b) is not None and f(a, b)


def _evidence_bound(s):
    exp = {r: p for r, p in _objs(s, "Experiment")}
    bad = []
    for lt, a, b in s["links"]:
        if lt == "PRODUCES" and a in exp and b in s["objects"]:
            ev = s["objects"][b]["props"]
            if (str(ev.get("experiment_version")) != str(exp[a].get("version")) or not ev.get("git_commit")
                    or not ev.get("environment")):
                bad.append(b)
    return bad


def _supported_needs_evidence(s):
    out = []
    for lt, v, h in s["links"]:
        if lt == "EVALUATES" and s["objects"].get(v, {}).get("props", {}).get("value") == "SUPPORTED":
            if not any(l2 == "SUPPORTS_OR_REFUTES" and h2 == h for l2, _e, h2 in s["links"]):
                out.append(v)
    return out


STATE = {
    "inventory-on-hand-nonnegative": lambda s: _bad_lots(s, lambda a, b: _num(a) is not None and a >= 0),
    "inventory-reserved-nonnegative": lambda s: _bad_lots(s, lambda a, b: _num(b) is not None and b >= 0),
    "inventory-on-hand-covers-reserved": lambda s: _bad_lots(s, _ok2(lambda a, b: a >= b)),
    "inventory-available-nonnegative": lambda s: _bad_lots(s, _ok2(lambda a, b: a - b >= 0)),
    "quality-vocabulary": lambda s: [r for r, p in _objs(s, "InventoryLot") if p.get("qualityStatus") not in ("OK", "QUARANTINE")],
    "work-order-status-vocabulary": lambda s: [r for r, p in _objs(s, "WorkOrder")
                                                if p.get("status") not in ("PLANNED", "RELEASED", "RUNNING", "DONE", "CANCELLED")],
    "verdict-vocabulary": lambda s: [r for r, p in _objs(s, "Verdict")
                                     if p.get("value") not in ("SUPPORTED", "REJECTED", "INCONCLUSIVE", "INVALID")],
    "running-requires-freeze-hash": lambda s: [r for r, p in _objs(s, "Hypothesis")
                                               if p.get("phase") in ("RUNNING", "EVALUATED") and not str(p.get("freeze_hash") or "").strip()],
    "supported-needs-evidence": _supported_needs_evidence,
    "evidence-bound-to-version-commit-environment": _evidence_bound,
}

# reasons: history = compares states in time; transition = constrains one committed operation; store = property of the store
NON_STATE = {
    "transfer-endpoints-disjoint": "transition", "transfer-safety-stock": "transition", "transfer-quarantine-blocked": "transition",
    "evidence-freshness": "transition", "transfer-approval-threshold": "transition", "expedite-approval-threshold": "transition",
    "high-priority-reschedule-approval": "transition", "no-effect-without-approval": "transition", "idempotency-key-unique": "store",
    "preregistration-complete-contract": "transition", "threshold-immutable-after-preregistration": "history",
    "falsifier-immutable-after-preregistration": "history", "evaluator-immutable-after-preregistration": "history",
    "evaluated-requires-evidence-or-reason": "transition", "verdict-machine-derived": "transition", "orphan-component-flagged-not-deleted": "transition",
    "lifecycle-order": "transition", "no-silent-stale-write": "transition", "conflicts-surface-explicitly": "transition",
    "ephemeral-state-marked": "store", "historical-binding-preserved": "history", "durable-actions-are-git-changes": "store",
    "rebuild-reproduces-state-hash": "store",
}


def violations(ops: dict, snap: dict) -> list[str]:
    """Ids of the ops-spec invariants the snapshot violates (state-checkable ones only)."""
    return sorted(i["id"] for i in ops["invariants"] if i["id"] in STATE and STATE[i["id"]](snap))
