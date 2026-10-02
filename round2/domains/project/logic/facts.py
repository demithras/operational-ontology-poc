"""Read-only fact extraction for the Project Ontology (graph walks over the Engine's read view)."""
from __future__ import annotations

from typing import Any

PHASES = ("DRAFT", "PREREGISTERED", "RUNNING", "EVALUATED", "SUPERSEDED")
VERDICTS = ("SUPPORTED", "REJECTED", "INCONCLUSIVE", "INVALID")
LIFECYCLE_ACTIONS = {"preregister_hypothesis": "PREREGISTERED", "start_run": "RUNNING",
                     "evaluate_hypothesis": "EVALUATED", "supersede_hypothesis": "SUPERSEDED"}
AUTHORITATIVE_PHASES = ("PREREGISTERED", "RUNNING", "EVALUATED", "SUPERSEDED")


def keys(recs) -> list:
    return [r["key"] for r in recs]


def out(view, link: str, t: str, key: Any) -> list:
    return keys(view.follow(link, t, key, "out"))


def inn(view, link: str, t: str, key: Any) -> list:
    return keys(view.follow(link, t, key, "in"))


def props(view, t: str, key: Any) -> dict | None:
    r = view.get(t, key)
    return None if r is None else r["props"]


def hypotheses(view) -> dict:
    return {r["key"]: r["props"] for r in view.list("Hypothesis")}


def experiments_of(view, hid: Any) -> list:
    return out(view, "TESTED_BY", "Hypothesis", hid)


def hypotheses_of_experiment(view, eid: Any) -> list:
    return inn(view, "TESTED_BY", "Experiment", eid)


def hypotheses_of_threshold(view, tid: Any) -> list:
    """Threshold <-GOVERNED_BY- Metric <-MEASURES- Experiment <-TESTED_BY- Hypothesis."""
    seen: list = []
    for m in inn(view, "GOVERNED_BY", "Threshold", tid):
        for e in inn(view, "MEASURES", "Metric", m):
            for h in hypotheses_of_experiment(view, e):
                if h not in seen:
                    seen.append(h)
    return seen


def thresholds_of_experiment(view, eid: Any) -> list:
    ts: list = []
    for m in out(view, "MEASURES", "Experiment", eid):
        for t in out(view, "GOVERNED_BY", "Metric", m):
            if t not in ts:
                ts.append(t)
    return ts


def evidence_of_experiment(view, eid: Any) -> list:
    return out(view, "PRODUCES", "Experiment", eid)


def evidence_count(view, hid: Any) -> int:
    return len(inn(view, "SUPPORTS_OR_REFUTES", "Hypothesis", hid))


def latest_experiment(view, hid: Any) -> str | None:
    """The tested-by experiment with the highest version (numeric when numeric, else lexicographic)."""
    exps = [(e, props(view, "Experiment", e)) for e in experiments_of(view, hid)]
    if not exps:
        return None

    def vkey(item):
        v = item[1]["version"]
        return (0, int(v), "") if str(v).isdigit() else (1, 0, str(v))
    return sorted(exps, key=vkey)[-1][0]


def active_components_missing(view) -> list:
    """Components with no EXISTS_FOR link to an active (not SUPERSEDED) hypothesis (= find_orphan_components)."""
    hy = hypotheses(view)
    orphans = []
    for c in sorted(keys(view.list("Component")), key=str):
        if not [h for h in out(view, "EXISTS_FOR", "Component", c) if hy.get(h, {}).get("phase") != "SUPERSEDED"]:
            orphans.append(c)
    return orphans


def planned(ctx, target: str) -> list:
    return [dict(p["payload"]) for p in ctx.planned if p["target"] == target]


def effective_hypotheses(ctx) -> dict:
    """Hypotheses as they would be after the planned (git) writes: {id: props with phase/freeze_hash overrides}."""
    hy = {k: dict(v) for k, v in hypotheses(ctx.view).items()}
    for p in planned(ctx, "Hypothesis"):
        k = p.get("$key", p.get("id"))
        base = hy.setdefault(k, {"id": k})
        base.update({f: v for f, v in p.items() if not f.startswith("$")})
    return hy


def target_hypotheses(ctx) -> list:
    """The hypotheses an action's inputs bind it to (subject of lifecycle preconditions and write policies)."""
    i, v = ctx.inputs, ctx.view
    a = ctx.action
    if a == "edit_threshold":
        return hypotheses_of_threshold(v, i["threshold"])
    if a == "new_experiment_version":
        return hypotheses_of_experiment(v, i["experiment"])
    if "hypothesis" in i:
        return [i["hypothesis"]]
    return []
