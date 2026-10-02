"""ENGINE_PREREG ordinary Domain 2 resources: Replication, REPLICATES, register_replication, count_replications.

``PATCH`` is declarative IR (applied to a COPY of the project contract; the Gate-0 file is never edited). The functions
below are DOMAIN LOGIC (the bindings the new Function / Action need) and live in this one new file so they can be counted
separately from endpoint / tool code, of which there is none.
"""
from __future__ import annotations

import copy

from domains._pack import load_ir
from domains.project.logic import facts

PATCH = {
    "object_types": [{"id": "Replication", "primary_key": "id", "implements": ["VersionedResearchObject"], "properties": [
        {"name": "id", "type": "string", "required": True, "immutable": True},
        {"name": "experiment_ref", "type": {"ref": "Experiment"}, "required": True, "immutable": True},
        {"name": "outcome", "type": "string", "required": True, "immutable": False}]}],
    "link_types": [{"id": "REPLICATES", "from": "Replication", "to": "Experiment", "from_cardinality": {"min": 1, "max": 1},
                    "to_cardinality": {"min": 0, "max": "*"}, "directed": True, "properties": []}],
    "functions": [{"id": "count_replications", "inputs": [{"name": "experiment", "type": {"ref": "Experiment"}, "required": True}],
                   "output": "integer", "purity": "NO_COMMITTED_BUSINESS_SIDE_EFFECT", "reads": ["REPLICATES"],
                   "implementation_ref": "fn:count_replications:v1", "determinism": "deterministic"}],
    "authority_rules": [{"id": "researcher-register-replication", "principal_selector": "role:researcher",
                         "capability": "action:register_replication", "resource_selector": "ProjectOntology:*", "effect": "allow",
                         "delegation_allowed": False}],
    "actions": [{"id": "register_replication", "inputs": [
        {"name": "id", "type": "string", "required": True}, {"name": "experiment_ref", "type": {"ref": "Experiment"}, "required": True},
        {"name": "outcome", "type": "string", "required": True}],
        "authority_refs": ["auth:researcher-register-replication", "auth:no-canonical-write-outside-git"], "policy_refs": [],
        "preconditions": ["experiment is EVALUATED"],
        "effects": [{"target": "Replication", "operation": "git_change", "fields": ["id", "experiment_ref", "outcome"]},
                    {"target": "REPLICATES", "operation": "git_change"}],
        "idempotency": "required", "outcome_predicate": "Git contains the replication and its REPLICATES link to the experiment",
        "compensation_action": None, "version": "v1"}],
}


def extended_ir() -> dict:
    ir = copy.deepcopy(load_ir("project"))
    for kind, items in PATCH.items():
        ir[kind] = ir[kind] + copy.deepcopy(items)
    return ir


# ---- domain logic (bindings) -------------------------------------------------------------------------------------------
def _count(view, args) -> int:
    return len(facts.inn(view, "REPLICATES", "Experiment", args["experiment"]))


def _experiment_evaluated(ctx) -> bool:
    ids = facts.hypotheses_of_experiment(ctx.view, ctx.inputs["experiment_ref"])
    return bool(ids) and all(facts.props(ctx.view, "Hypothesis", i)["phase"] == "EVALUATED" for i in ids)


def _link_payload(ctx) -> dict:
    return {"$src": ctx.inputs["id"], "$dst": ctx.inputs["experiment_ref"]}


def _outcome(ctx):
    want = [{"id": ctx.inputs["id"], "experiment_ref": ctx.inputs["experiment_ref"], "outcome": ctx.inputs["outcome"]},
            {"$src": ctx.inputs["id"], "$dst": ctx.inputs["experiment_ref"]}]
    seen = {o["data"].get("sha") for o in ctx.observations if o.get("observation_type") == "GitCommitObserved"}
    for n, row in enumerate(want):
        resp = ctx.responses.get(f"{ctx.execution}/e{n}")
        if resp is None or resp.get("commit") not in seen:
            return None
        if any(resp["row"].get(k) != v for k, v in row.items()):
            return False
    return True


def extend(b) -> None:
    """Bind the logic the four new resources need (called by domains.project.pack.build_pack(extend=...))."""
    b.bind("function", "fn:count_replications:v1", _count)
    b.bind("precondition", "experiment is EVALUATED", _experiment_evaluated)
    b.bind("payload", "register_replication#1", _link_payload)
    b.bind("outcome_predicate", "Git contains the replication and its REPLICATES link to the experiment", _outcome)
