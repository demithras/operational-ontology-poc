"""Map a generated op (case dict) to the Engine action call and to the baseline change helper."""
from __future__ import annotations

from baselines.h18_fileonly import actions as A
from baselines.h18_fileonly.ci import check
from baselines.h18_fileonly.repo import Model


def latest_experiment_id(objs: set | list, base: str) -> str:
    vers = sorted((int(str(k).split("@v")[1]) if "@v" in str(k) else 1, k) for k in objs if k == base or str(k).startswith(base + "@v"))
    return vers[-1][1]


def engine_call(case: dict, op: dict, exp_ids: list) -> tuple[str, dict]:
    s, f, k = case["subject"], case["facts"], op["k"]
    if k == "preregister":
        return "preregister_hypothesis", {"hypothesis": s, "freeze_hash": op["freeze_value"]}
    if k == "edit_threshold":
        return "edit_threshold", {"threshold": f["threshold"], "value": op["value"]}
    if k == "new_version":
        return "new_experiment_version", {"experiment": f["exp"] if op["exp"] == "base" else latest_experiment_id(exp_ids, f["exp"]), "contract_version": f["cv"]}
    if k == "start":
        return "start_run", {"hypothesis": s}
    if k == "attach":
        return "attach_evidence", {"hypothesis": s, "evidence": op["ev"]}
    if k == "evaluate":
        return "evaluate_hypothesis", {"hypothesis": s}
    if k == "forced_verdict":
        return "evaluate_hypothesis", {"hypothesis": s, "verdict": op["value"]}
    if k == "supersede":
        return "supersede_hypothesis", {"hypothesis": s, "successor": s if op["succ"] == "self" else f["other"]}
    if k == "flag":
        return "flag_orphan_component", {"component": op["cmp"]}
    if k == "decision":
        return "record_decision", {"decision": case["decision"]["id"], "contract_version": f["cv"]}
    return "create_hypothesis", {"claim": op["claim"]}


def baseline_apply(case: dict, op: dict, files: dict, evaluators: dict) -> tuple[bool, dict, list]:
    """(accepted, files after, reasons). The helper may refuse (guard) or the CI gate may reject the resulting diff."""
    m, s, f, k = Model(files), case["subject"], case["facts"], op["k"]
    try:
        if k == "preregister":
            new = A.preregister(files, m, s, op["freeze_value"])
        elif k == "edit_threshold":
            new = A.edit_threshold(files, m, f["threshold"], op["value"])
        elif k == "new_version":
            exp = f["exp"] if op["exp"] == "base" else latest_experiment_id([e for (t, e) in m.objs if t == "Experiment"], f["exp"])
            new = A.new_version(files, m, exp, f["cv"])
        elif k == "start":
            new = A.start(files, m, s)
        elif k == "attach":
            new = A.attach(files, m, s, op["ev"])
        elif k == "evaluate":
            new = A.evaluate(files, m, s, f["commit"], evaluators)
        elif k == "forced_verdict":
            new = A.forced_verdict(files, m, s, f["commit"], op["value"])
        elif k == "supersede":
            new = A.supersede(files, m, s, s if op["succ"] == "self" else f["other"])
        elif k == "flag":
            new = A.flag(files, m, op["cmp"])
        elif k == "decision":
            new = A.decide(files, m, case["decision"]["id"], f["cv"])
        else:
            new = A.create(files, m, op["claim"])
    except A.Refused as e:
        return False, files, [f"guard: {e}"]
    bad = check(files, new, evaluators)
    return (not bad), (new if not bad else files), bad
