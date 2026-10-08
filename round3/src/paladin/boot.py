"""Build one Paladin Engine for a domain from (IR package, neutral specs, world). No domain branches here: the domain
is data (IR file, logic bindings module, adapter kind) in `DOMAINS`."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from paladin.authcompile import compile_ir, principals, shadow_principals
from paladin.engine import Engine, LogicBindings
from paladin.engine.effects import AdapterRegistry
from paladin.worldbridge import WorldExternalAdapter, WorldGitAdapter

HERE = Path(__file__).resolve().parent
DOMAINS = {"manufacturing": {"ir": "domains/manufacturing/ir.json"}, "project": {"ir": "domains/project/ir.v3.json"}}

NEUTRAL_EVALUATOR = "neutral:evidence-present-v1"


def neutral_evaluator(experiment: dict, evidence: list, hypothesis: dict) -> dict:
    """Spec config.evaluators['neutral:evidence-present-v1']: protocol_valid = freeze_hash non-blank;
    required_evidence_complete = sample_sufficient = support_hit = (evidence_count >= 1); reject_hit = false."""
    n = hypothesis.get("_evidence_count", 0)
    return {"protocol_valid": bool(str(hypothesis.get("freeze_hash") or "").strip()), "required_evidence_complete": n >= 1,
            "sample_sufficient": n >= 1, "reject_hit": False, "support_hit": n >= 1}


def load_ir(domain: str) -> dict:
    return json.loads((HERE / DOMAINS[domain]["ir"]).read_text())


def bindings_for(domain: str, ir: dict) -> LogicBindings:
    if domain == "manufacturing":
        from paladin.domains.manufacturing.logic import build_bindings
        return build_bindings()
    from paladin.domains.project.logic import build_bindings
    return build_bindings(ir, {NEUTRAL_EVALUATOR: neutral_evaluator})


@dataclass
class Booted:
    engine: Engine
    ir: dict
    principals: dict
    shadow: dict | None = None


def boot(domain: str, ops_spec: dict, auth_spec: dict, handle_factory: Callable, service_handle: Any,
         clock: Callable[[], int], pre_apply: Callable[[], None] = lambda: None) -> Booted:
    ir = compile_ir(load_ir(domain), auth_spec, ops_spec)
    holder: dict = {}
    if domain == "manufacturing":
        specs: dict = {}
        for op in ops_spec["operations"]:
            for e in op["effects"]:
                if e["kind"] == "external":
                    specs.setdefault(e["adapter"], {})[op["name"]] = e
        inputs_of = lambda xid: holder["engine"]._executions[xid]["inputs"]  # noqa: E731 - read-only adapter helper
        adapters = {("external_call", s): WorldExternalAdapter(s, handle_factory, per_action, inputs_of, pre_apply)
                    for s, per_action in specs.items()}
    else:
        fields: dict = {}  # (action, kind, type) -> exactly the props the ops spec lists for that effect (R-3 creates; updates likewise)
        for op in ops_spec["operations"]:
            for e in op["effects"]:
                if e["kind"] in ("create", "update"):
                    fields.setdefault((op["name"], e["kind"], e["type"]), set()).update(e["props"])
        git = WorldGitAdapter(service_handle, fields, pre_apply)
        adapters = {("git_change", "*"): git}
    engine = Engine(ir, bindings_for(domain, ir), adapters, clock=clock)
    holder["engine"] = engine
    if domain == "project":
        git.attach(engine.model)
    pr = principals(auth_spec)
    sh = shadow_principals(pr)
    for p in list(pr.values()) + list(sh.values()):
        engine.register_principal(p)
    return Booted(engine, ir, pr, sh)
