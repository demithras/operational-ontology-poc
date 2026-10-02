"""EOO implementation of H18 task classes TC2 (forensic queries) and TC3 (model change): IR patch + domain logic."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from domains._pack import load_ir
from domains.project.logic import facts

PATCH = json.loads((Path(__file__).parent / "tc_patch.json").read_text())


def patched_ir() -> dict:
    ir = copy.deepcopy(load_ir("project"))
    for kind, items in PATCH.items():
        ir[kind] = ir[kind] + copy.deepcopy(items)
    return ir


def dependency_ops(reader) -> list:
    """DEPENDS_ON links read from the committed contracts' upstream_dependencies (TC2 q3 needs them modelled)."""
    ops = []
    for h in range(15, 23):
        c = json.loads(reader(f"hypotheses/h{h}/contract.json"))
        ops += [{"op": "link", "type": "DEPENDS_ON", "src": ["Hypothesis", c["id"]], "dst": ["Hypothesis", d], "props": {}}
                for d in c.get("upstream_dependencies", [])]
    return ops


def _latest_verdict(view, hid):
    vs = facts.inn(view, "EVALUATES", "Hypothesis", hid)
    return max(vs, key=lambda v: int(str(v).rsplit("-", 1)[1])) if vs else None


def evidence_of_verdict(view, a) -> dict:
    hid, v = a["hypothesis"], _latest_verdict(view, a["hypothesis"])
    exp = facts.latest_experiment(view, hid)
    ev = sorted(facts.evidence_of_experiment(view, exp))
    return {"verdict": facts.props(view, "Verdict", v)["value"], "experiment": exp, "evidence": ev,
            "commits": sorted({facts.props(view, "Evidence", e)["git_commit"] for e in ev})}


def blocked_hypotheses(view, a) -> list:
    def supported(h):
        v = _latest_verdict(view, h)
        return v is not None and facts.props(view, "Verdict", v)["value"] == "SUPPORTED"
    return sorted(h for h in facts.hypotheses(view) if not all(supported(u) for u in facts.out(view, "DEPENDS_ON", "Hypothesis", h)))


def _evaluated(ctx) -> bool:
    ids = facts.hypotheses_of_experiment(ctx.view, ctx.inputs["experiment_ref"])
    return bool(ids) and all(facts.props(ctx.view, "Hypothesis", i)["phase"] == "EVALUATED" for i in ids)


def _replication_rows(ctx) -> list:
    i = ctx.inputs
    return [{"id": i["id"], "experiment_ref": i["experiment_ref"], "outcome": i["outcome"]}, {"$src": i["id"], "$dst": i["experiment_ref"]}]


def _replication_outcome(ctx):
    seen = {o["data"].get("sha") for o in ctx.observations if o.get("observation_type") == "GitCommitObserved"}
    for n, want in enumerate(_replication_rows(ctx)):
        resp = ctx.responses.get(f"{ctx.execution}/e{n}")
        if resp is None or resp.get("commit") not in seen:
            return None
        if any(resp["row"].get(k) != v for k, v in want.items()):
            return False
    return True


def extend(b) -> None:
    b.bind("function", "fn:evidence_of_verdict:v1", evidence_of_verdict)
    b.bind("function", "fn:blocked_hypotheses:v1", blocked_hypotheses)
    b.bind("function", "fn:count_replications:v1", lambda view, a: len(facts.inn(view, "REPLICATES", "Experiment", a["experiment"])))
    b.bind("precondition", "experiment is EVALUATED", _evaluated)
    b.bind("payload", "register_replication#1", lambda ctx: _replication_rows(ctx)[1])
    b.bind("outcome_predicate", "Git contains the replication and its REPLICATES link to the experiment", _replication_outcome)
