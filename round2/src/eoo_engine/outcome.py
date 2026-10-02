"""Outcome observation, reconciliation and crash recovery.

Observations come only from adapters (``observations()``), correlated by execution id, validated
against the IR ObservationType named in the observation, and journaled before use. The action's
outcome predicate then decides: True -> RECONCILED_SUCCESS, False -> RECONCILED_FAILED,
None / error -> OUTCOME_UNKNOWN (reconcile() may be called again later).
"""
from __future__ import annotations

from . import effects, gates, pipeline
from .authority import Principal
from .canon import digest, to_plain
from .errors import InvalidRequest

OBS_TYPE, OBS_EXEC, OBS_DATA = "observation_type", "execution", "data"


def _adapters_of(eng, spec) -> list:
    seen, out = set(), []
    for eff in spec.effects:
        if effects.routes_to_adapter(eff):
            ad = eng.adapters.lookup(eff.operation, eff.target)
            if ad is not None and id(ad) not in seen:
                seen.add(id(ad))
                out.append(ad)
    return out


def collect(eng, spec, rec) -> bool:
    """Pull new observations for this execution; True when something new was journaled."""
    known = {o["digest"] for o in rec["observations"]} | {o["digest"] for o in rec["rejected_observations"]}
    new = False
    for ad in _adapters_of(eng, spec):
        for raw in list(ad.observations()):
            try:
                obs = to_plain(dict(raw))
            except (TypeError, ValueError):
                continue
            if obs.get(OBS_EXEC) != rec["exec"]:
                continue
            d = digest(obs)
            if d in known:
                continue
            known.add(d)
            otype = obs.get(OBS_TYPE)
            if not isinstance(otype, str) or eng.model.get("observation_types", otype) is None:
                probs = [f"unknown observation type {otype!r}"]
            else:
                probs = eng.dispatch("observation_types", "validate", otype, data=obs.get(OBS_DATA))
            entry = {"digest": d, "observation": obs, "at": eng.now()}
            (rec["rejected_observations"] if probs else rec["observations"]).append(
                {**entry, "problems": probs} if probs else entry)
            new = True
    if new:
        eng.record(rec, rec["state"], note="observations")
    return new


def observe_and_reconcile(eng, spec, rec) -> dict:
    collect(eng, spec, rec)
    ctx = gates.make_ctx(eng, spec, rec, observations=[o["observation"] for o in rec["observations"]],
                         responses=rec["responses"])
    try:
        verdict = eng.bindings.get("outcome_predicate", spec.outcome_predicate)(ctx)
        err = None if verdict in (True, False, None) else f"outcome predicate returned {verdict!r}"
    except Exception as exc:
        verdict, err = None, f"{type(exc).__name__}: {exc}"
    if err:
        verdict = None
    rec["observed"] = {"verdict": verdict, "error": err, "observation_count": len(rec["observations"])}
    state = {True: "RECONCILED_SUCCESS", False: "RECONCILED_FAILED", None: "OUTCOME_UNKNOWN"}[verdict]
    return eng.record(rec, state, note="reconciled")


def reconcile(eng, spec, execution: str) -> dict:
    rec = eng.executions.get(execution)
    if rec is None or rec["action"] != spec.rid or rec["state"] not in ("EFFECTS_COMMITTED", "OUTCOME_UNKNOWN"):
        raise InvalidRequest(f"{execution!r} cannot be reconciled")
    return observe_and_reconcile(eng, spec, rec)


def recover(eng) -> list[dict]:
    """Deterministically finish what a crash interrupted (journal order). Never re-calls an adapter
    whose intent was journaled without a response: that effect is uncertain -> OUTCOME_UNKNOWN."""
    report = []
    for xid in list(eng.executions):
        rec = eng.executions[xid]
        before = rec["state"]
        if before not in ("PROPOSED", "APPROVED", "EXECUTING", "EFFECTS_COMMITTED"):
            continue
        spec = eng.model.get("actions", rec["action"])
        if before == "PROPOSED":  # crashed before the gate decision: no effect exists yet, decide now
            shown = rec["presented"]
            pipeline.run_gates(eng, spec, rec, Principal.from_plain(shown) if isinstance(shown, dict)
                               and "pid" in shown else shown)
        elif before == "EXECUTING" and any(i not in rec["responses"] for i in rec["intents"]):
            eng.record(rec, "OUTCOME_UNKNOWN", note="crash between adapter intent and response; effect uncertain")
        elif before in ("APPROVED", "EXECUTING"):
            eng.dispatch("actions", "execute", spec.rid, execution=xid)
        else:
            eng.dispatch("actions", "reconcile", spec.rid, execution=xid)
        report.append({"exec": xid, "from": before, "to": eng.executions[xid]["state"]})
    return report
