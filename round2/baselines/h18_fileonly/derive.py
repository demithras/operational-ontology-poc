"""Machine-derived verdict of a hypothesis: latest experiment + attached evidence + its registered evaluator."""
from __future__ import annotations

from hdd.verdict import CommonEvaluation, evaluate_common


def latest_experiment(m, hid):
    exps = m.out("TESTED_BY", hid)
    return max(exps, key=lambda e: int(m.props("Experiment", e)["version"])) if exps else None


def derive(m, hid, evaluators) -> str:
    h, eid = m.props("Hypothesis", hid), latest_experiment(m, hid)
    flags = dict(protocol_valid=True, required_evidence_complete=False, sample_sufficient=False, reject_hit=False, support_hit=False)
    if eid is not None:
        e = {"id": eid, **m.props("Experiment", eid)}
        ev = [{"id": k, **m.props("Evidence", k)} for k in m.out("PRODUCES", eid) if m.props("Evidence", k)["experiment_version"] == e["version"]]
        if ev:
            flags = dict(evaluators[e["evaluator_ref"]](e, ev, {"id": hid, **h}))
    flags["protocol_valid"] = flags["protocol_valid"] and bool(h.get("freeze_hash"))
    return evaluate_common(CommonEvaluation(**flags)).value
