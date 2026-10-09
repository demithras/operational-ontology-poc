"""Policy expression bindings of the Project Ontology (pred(ctx) -> bool, True = the policy applies).

The seven ``docs/04`` hard rules follow src/hdd/project_lifecycle_reference.py; the four ``docs/05`` policies are
modelled structurally (the docs state the property, not a predicate: each reading is spelled out in
provenance-logic.md and is *modelled, not read from a source*).
"""
from __future__ import annotations

from . import facts, payloads
from .lifecycle import legal_transition


def contract_complete(view, hid, freeze_hash=None) -> bool:
    """Preregistration completeness (docs/04 hard rule 1): claim, >=1 rival, >=1 prediction, >=1 falsifier, an experiment
    with evidence schema and evaluator."""
    h = facts.props(view, "Hypothesis", hid)
    if h is None or not str(h.get("claim", "")).strip():
        return False
    for link in ("HAS_RIVAL", "PREDICTS", "FALSIFIED_BY"):
        if not facts.out(view, link, "Hypothesis", hid):
            return False
    exps = [facts.props(view, "Experiment", e) for e in facts.experiments_of(view, hid)]
    if not any(str(e.get("evidence_schema_ref", "")).strip() and str(e.get("evaluator_ref", "")).strip() for e in exps):
        return False
    return freeze_hash is None or bool(str(freeze_hash).strip())


def _incomplete(ctx) -> bool:
    # G3-E31(a): the formal `when` binds - a blank freeze_hash is the precondition freeze-hash-present (INVALID), not a deny
    return not contract_complete(ctx.view, ctx.inputs["hypothesis"])


def _threshold_edit_denied(ctx) -> bool:
    if ctx.action == "edit_threshold":
        hy = facts.hypotheses(ctx.view)
        targets = facts.target_hypotheses(ctx)  # ops-spec: not all_have(..., nonempty:true) - an empty/absent set denies
        return not (targets and all(hy.get(h, {}).get("phase") == "DRAFT" for h in targets))
    new_id = payloads.new_experiment_ids(ctx.view, ctx.inputs)[1]  # a new version must be new, never an overwrite
    return ctx.view.get("Experiment", new_id) is not None


def _running_without_freeze(ctx) -> bool:
    h = facts.props(ctx.view, "Hypothesis", ctx.inputs["hypothesis"])
    return not (h and str(h.get("freeze_hash") or "").strip())


def make(deriver, reader) -> dict:
    def evaluated_without_evidence(ctx) -> bool:
        hid = ctx.inputs["hypothesis"]
        return ctx.call("evidence_count", {"hypothesis": hid}) == 0 and \
            ctx.call("derive_verdict", {"hypothesis": hid}) not in ("INCONCLUSIVE", "INVALID")

    def verdict_not_machine_derived(ctx) -> bool:
        return "verdict" in ctx.inputs or ctx.call("derive_verdict", {"hypothesis": ctx.inputs["hypothesis"]}) \
            not in facts.VERDICTS

    def evidence_unbound(ctx) -> bool:
        from .actions import evidence_pinned
        return not evidence_pinned(ctx.view, ctx.inputs["hypothesis"], ctx.inputs["evidence"])

    def orphan(ctx) -> bool:
        return ctx.inputs["component"] in ctx.call("find_orphan_components", {})

    def stale_write(ctx) -> bool:
        """A newer Git version exists: some hypothesis this action would write already has a successor."""
        return any(facts.out(ctx.view, "SUPERSEDED_BY", "Hypothesis", h) for h in facts.target_hypotheses(ctx))

    def conflicting_change(ctx) -> bool:
        if ctx.action != "supersede_hypothesis":
            return False
        succ, hid = ctx.inputs["successor"], ctx.inputs["hypothesis"]
        return succ == hid or any(h != hid for h in facts.inn(ctx.view, "SUPERSEDED_BY", "Hypothesis", succ))

    def ephemeral(ctx) -> bool:
        def walk(v):
            if isinstance(v, str):
                return v.startswith("ephemeral:")
            if isinstance(v, (list, tuple)):
                return any(walk(x) for x in v)
            if hasattr(v, "values"):
                return any(walk(x) for x in v.values())
            return False
        return walk(ctx.inputs)

    def historical_rebinding(ctx) -> bool:
        v, i = ctx.view, ctx.inputs
        if ctx.action == "attach_evidence":
            ev = facts.props(v, "Evidence", i["evidence"])
            owners = facts.inn(v, "PRODUCES", "Evidence", i["evidence"])
            return any((facts.props(v, "Experiment", o) or {}).get("version") != (ev or {}).get("experiment_version") for o in owners)
        if ctx.action == "new_experiment_version":
            return v.get("ContractVersion", payloads.new_experiment_ids(v, i)[3]) is not None
        if ctx.action == "record_decision":
            cv = facts.props(v, "ContractVersion", i["contract_version"]) or {}  # absent target: empty facts (G3-E17/E20)
            return not str(cv.get("git_commit") or "").strip()  # an unbound contract version cannot be changed by a decision
        return False

    def legal(ctx) -> bool:
        target = facts.LIFECYCLE_ACTIONS.get(ctx.action)
        ids = facts.target_hypotheses(ctx)
        hy = facts.hypotheses(ctx.view)
        return target is not None and len(ids) == 1 and ids[0] in hy and legal_transition(hy[ids[0]].get("phase"), target)

    return {
        "docs/04#preregistration-completeness": _incomplete,
        "docs/04#threshold-immutable": _threshold_edit_denied,
        "docs/04#running-needs-freeze-hash": _running_without_freeze,
        "docs/04#evaluated-needs-evidence": evaluated_without_evidence,
        "docs/04#verdict-machine-derived": verdict_not_machine_derived,
        "docs/04#evidence-binding": evidence_unbound,
        "docs/04#orphan-classification": orphan,
        "docs/05#stale-write": stale_write,
        "docs/05#explicit-conflict": conflicting_change,
        "docs/05#ephemeral-state": ephemeral,
        "docs/05#historical-binding": historical_rebinding,
        "docs/04#lifecycle-order": legal,
    }
