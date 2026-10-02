"""Preconditions, outcome predicates and payload bindings of the Project Ontology (all keyed by their IR text)."""
from __future__ import annotations

from . import facts, payloads


def _phase_all(ctx, wanted) -> bool:
    """Every hypothesis the action is bound to (at least one) satisfies ``wanted(phase)``."""
    hy = facts.hypotheses(ctx.view)
    ids = facts.target_hypotheses(ctx)
    return bool(ids) and all(i in hy and wanted(hy[i].get("phase")) for i in ids)


def _freeze_hash_exists(ctx) -> bool:
    if "freeze_hash" in ctx.inputs:  # preregister_hypothesis: the freeze hash is a request input
        return bool(str(ctx.inputs["freeze_hash"]).strip())
    hy = facts.hypotheses(ctx.view)  # start_run: the hypothesis was preregistered with one
    return all(bool(hy[i].get("freeze_hash")) for i in facts.target_hypotheses(ctx)) and bool(facts.target_hypotheses(ctx))


def evidence_pinned(view, hid, evidence_id) -> bool:
    ev = facts.props(view, "Evidence", evidence_id)
    if ev is None or not all(str(ev.get(k) or "").strip() for k in
                             ("payload_hash", "git_commit", "experiment_version", "environment")):
        return False
    return payloads.experiment_of_evidence(view, hid, ev) is not None


def _evaluate_precondition(ctx) -> bool:
    hid = ctx.inputs["hypothesis"]
    if ctx.call("evidence_count", {"hypothesis": hid}) >= 1:
        return True
    return ctx.call("derive_verdict", {"hypothesis": hid}) in ("INCONCLUSIVE", "INVALID")


PRECONDITIONS = {
    "claim is non-empty": lambda c: bool(str(c.inputs["claim"]).strip()),
    "phase == DRAFT": lambda c: _phase_all(c, lambda p: p == "DRAFT"),
    "freeze_hash exists": _freeze_hash_exists,
    "phase != DRAFT": lambda c: _phase_all(c, lambda p: p != "DRAFT"),
    "phase == PREREGISTERED": lambda c: _phase_all(c, lambda p: p == "PREREGISTERED"),
    "phase == RUNNING": lambda c: _phase_all(c, lambda p: p == "RUNNING"),
    "phase == EVALUATED": lambda c: _phase_all(c, lambda p: p == "EVALUATED"),
    "evidence is pinned to experiment version, commit and environment":
        lambda c: evidence_pinned(c.view, c.inputs["hypothesis"], c.inputs["evidence"]),
    "evidence_count(hypothesis) >= 1 or an explicit INCONCLUSIVE/INVALID reason is given": _evaluate_precondition,
    "rationale is non-empty":
        lambda c: bool(str((facts.props(c.view, "Decision", c.inputs["decision"]) or {}).get("rationale", "")).strip()),
    "component is returned by find_orphan_components":
        lambda c: c.inputs["component"] in c.call("find_orphan_components", {}),
}

_GIT = {
    "create_hypothesis": "Git contains the hypothesis contract at the expected commit with phase == DRAFT",
    "edit_threshold": "Git contains the new threshold value while the hypothesis phase is still DRAFT",
    "preregister_hypothesis": "Git contains preregistered contract at expected commit",
    "new_experiment_version": "Git contains a new Experiment row with a new version and the matching ContractVersion; "
                              "the old experiment version is unchanged",
    "start_run": "Git contains the hypothesis with phase == RUNNING at the expected commit",
    "attach_evidence": "Git contains the evidence artifact bound to the experiment version, commit and environment",
    "evaluate_hypothesis": "Git contains a Verdict whose value equals derive_verdict(hypothesis) and the hypothesis "
                           "with phase == EVALUATED",
    "supersede_hypothesis": "Git contains the hypothesis with phase == SUPERSEDED and a SUPERSEDED_BY link to the successor",
    "record_decision": "Git contains the decision and its CHANGES link to the contract version",
    "flag_orphan_component": "Git contains the component with orphan_flagged == true; the component is not deleted",
}


def _outcome(fn_name: str, deriver, reader, n_effects: int):
    """True when every effect's Git commit was observed and its stored row equals the expected payload; False when Git
    holds something different; None (unknown) while a response or a commit observation is missing."""
    expected_fn = payloads.PAYLOAD_FNS[fn_name]

    def predicate(ctx):
        expected = expected_fn(ctx, deriver, reader)[:n_effects]  # the IR version decides how many effects exist
        seen = {o["data"].get("sha") for o in ctx.observations if o.get("observation_type") == "GitCommitObserved"}
        for i, want in enumerate(expected):
            resp = ctx.responses.get(f"{ctx.execution}/e{i}")
            if resp is None or resp.get("commit") not in seen:
                return None
            row = resp.get("row", {})
            if any(row.get(k) != v for k, v in want.items()):
                return False
        return True
    return predicate


def bindings(deriver, reader, ir: dict) -> dict:
    out = {}
    for act in ir["actions"]:
        fn = payloads.PAYLOAD_FNS[act["id"]]
        for i in range(len(act["effects"])):
            out[f"{act['id']}#{i}"] = (lambda f, idx: lambda ctx: f(ctx, deriver, reader)[idx])(fn, i)
    n_eff = {a["id"]: len(a["effects"]) for a in ir["actions"]}
    return {"precondition": PRECONDITIONS,
            "outcome_predicate": {text: _outcome(name, deriver, reader, n_eff[name]) for name, text in _GIT.items()},
            "payload": out}
