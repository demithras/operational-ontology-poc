"""Load a validated IR package into a registry keyed by resource KIND.

``DISPATCH_TABLE`` maps each kernel kind name to its handler; it is the only place where the Engine
decides what to do with a resource, and it decides by kind only (never by resource id). Each handler
has ``compile(resource, model) -> (spec, [Unbound])`` and ``ops``: {operation name -> fn(engine, spec, **kw)}.
"""
from __future__ import annotations

from eoo_ir import validate as ir_validate

from . import authority, effects, functions, gates, outcome, pipeline, queries
from .errors import LoadError, Unbound
from .model import (ActionSpec, ConstraintSpec, EffectSpec, FnSpec, IfaceSpec, LinkSpec, Model, ObjSpec, ObsSpec,
                    Param, PolicySpec, RuleSpec)


def _params(raw: list) -> tuple:
    return tuple(Param(p["name"], p["type"], p.get("required", True)) for p in raw)


def _props(raw: list) -> dict:
    return {p["name"]: p for p in raw}


class Handler:
    kind = ""
    ops: dict = {}

    def compile(self, r: dict, model: Model):
        raise NotImplementedError


class InterfaceHandler(Handler):
    kind = "interfaces"
    ops = {"query": lambda eng, spec, **kw: queries.list_objects(eng.state(), spec.rid)}

    def compile(self, r, model):
        model.implementers.setdefault(r["id"], set())
        return IfaceSpec(r["id"], tuple(r["required_properties"]), tuple(r["required_links"]),
                         tuple(r["capabilities"])), []


class ObjectTypeHandler(Handler):
    kind = "object_types"
    ops = {"get": lambda eng, spec, key: queries.get(eng.state(), spec.rid, key),
           "list": lambda eng, spec: queries.list_objects(eng.state(), spec.rid)}

    def compile(self, r, model):
        for iface in r["implements"]:
            model.implementers.setdefault(iface, set()).add(r["id"])
        return ObjSpec(r["id"], r["primary_key"], _props(r["properties"]), tuple(r["implements"])), []


class LinkTypeHandler(Handler):
    kind = "link_types"
    ops = {"follow": lambda eng, spec, t, key, direction="out": queries.follow(eng.state(), spec.rid, t, key, direction)}

    def compile(self, r, model):
        fc, tc = r["from_cardinality"], r["to_cardinality"]
        return LinkSpec(r["id"], r["from"], r["to"], fc["max"], tc["max"], fc["min"], tc["min"],
                        _props(r.get("properties", []))), []


class ObservationTypeHandler(Handler):
    kind = "observation_types"
    ops = {"validate": lambda eng, spec, data: gates.observation_problems(eng, spec, data)}

    def compile(self, r, model):
        return ObsSpec(r["id"], r["subject_type"], _props(r["properties"])), []


class FunctionHandler(Handler):
    kind = "functions"
    ops = {"call": lambda eng, spec, args, state=None, view=None: functions.call(
        spec, args, state or eng.state(), view or eng.read_view(state), eng.bindings)}

    def compile(self, r, model):
        spec = FnSpec(r["id"], _params(r["inputs"]), r["output"], r["implementation_ref"])
        return spec, [Unbound("function", r["implementation_ref"], f"functions.{r['id']}")]


class PolicyHandler(Handler):
    kind = "policies"
    ops = {"evaluate": lambda eng, spec, ctx: gates.bool_logic(eng.bindings.get("policy", spec.expr), ctx)}

    def compile(self, r, model):
        return PolicySpec(r["id"], r["decision"], r["expression_ref"], r["version"]), \
            [Unbound("policy", r["expression_ref"], f"policies.{r['id']}")]


class AuthorityRuleHandler(Handler):
    kind = "authority_rules"
    ops = {"decide": lambda eng, spec, refs, principal, capability, resources, view: authority.evaluate(
        refs, principal, capability, resources, eng.model, eng.bindings, view)}

    def compile(self, r, model):
        look = authority.type_lookup(model)
        ps = authority.parse_principal(r["principal_selector"], look)
        rs = authority.parse_resource(r["resource_selector"], look)
        need = [Unbound(k, sel[1], f"authority_rules.{r['id']}")
                for k, sel in (("principal_selector", ps), ("resource_selector", rs)) if sel[0] == "bound"]
        return RuleSpec(r["id"], ps, r["capability"], rs, r["effect"], r.get("delegation_allowed", False),
                        r["principal_selector"], r["resource_selector"]), need


class ConstraintHandler(Handler):
    kind = "constraints"
    ops = {"evaluate": lambda eng, spec, ctx: gates.bool_logic(eng.bindings.get("constraint", spec.expr), ctx)}

    def compile(self, r, model):
        return ConstraintSpec(r["id"], r["scope"], r["expression_ref"], r["severity"]), \
            [Unbound("constraint", r["expression_ref"], f"constraints.{r['id']}")]


class ActionHandler(Handler):
    kind = "actions"
    ops = {"propose": lambda eng, spec, **kw: pipeline.propose(eng, spec, **kw),
           "approve": lambda eng, spec, **kw: pipeline.decide_approval(eng, spec, approve=True, **kw),
           "reject": lambda eng, spec, **kw: pipeline.decide_approval(eng, spec, approve=False, **kw),
           "execute": lambda eng, spec, **kw: pipeline.execute(eng, spec, **kw),
           "reconcile": lambda eng, spec, **kw: outcome.reconcile(eng, spec, **kw)}

    def compile(self, r, model):
        where = f"actions.{r['id']}"
        need: list[Unbound] = []
        auth = []
        for ref in r["authority_refs"]:
            local = ref[len("auth:"):] if ref.startswith("auth:") and model.get("authority_rules", ref[5:]) else None
            auth.append((ref, local))
            if local is None:
                need.append(Unbound("authority_import", ref, where))
        pols = []
        for ref in r["policy_refs"]:
            local = ref[len("policy:"):] if ref.startswith("policy:") and model.get("policies", ref[7:]) else None
            pols.append((ref, local))
            if local is None:
                need.append(Unbound("policy_import", ref, where))
        need += [Unbound("precondition", p, where) for p in r["preconditions"]]
        need.append(Unbound("outcome_predicate", r["outcome_predicate"], where))
        effs = []
        for i, e in enumerate(r["effects"]):
            kind, plan = effects.plan_effect(r, e, model)
            eff = EffectSpec(i, e["operation"], e["target"], tuple(e["fields"]) if "fields" in e else None, kind, plan)
            effs.append(eff)
            if plan is None:
                need.append(Unbound("payload", f"{r['id']}#{i}", f"{where}.effects[{i}]"))
            if effects.routes_to_adapter(eff):
                need.append(Unbound("adapter", f"{eff.operation}:{eff.target}", f"{where}.effects[{i}]"))
        spec = ActionSpec(r["id"], r["version"], _params(r["inputs"]), tuple(auth), tuple(pols),
                          tuple(r["preconditions"]), tuple(effs), r["idempotency"], r["outcome_predicate"],
                          r.get("compensation_action"))
        return spec, need


# Kind name -> handler. Order = compile order (dependencies first). Audited by tests/engine.
DISPATCH_TABLE: dict[str, Handler] = {
    "interfaces": InterfaceHandler(),
    "object_types": ObjectTypeHandler(),
    "link_types": LinkTypeHandler(),
    "observation_types": ObservationTypeHandler(),
    "functions": FunctionHandler(),
    "policies": PolicyHandler(),
    "authority_rules": AuthorityRuleHandler(),
    "constraints": ConstraintHandler(),
    "actions": ActionHandler(),
}


def load_model(pkg: dict) -> Model:
    """Validate (eoo_ir) and compile every resource through DISPATCH_TABLE."""
    errs = ir_validate(pkg)
    if errs:
        raise LoadError(errs)
    resource_kinds = [k for k, v in pkg.items() if isinstance(v, list) and k != "imports"]
    unknown = [k for k in resource_kinds if k not in DISPATCH_TABLE]
    if unknown:
        raise LoadError([f"no handler for resource kind {k!r}" for k in unknown])
    model = Model(pkg["package_id"], pkg["version"], tuple(pkg.get("imports", [])))
    for kind in DISPATCH_TABLE:
        handler = DISPATCH_TABLE[kind]
        table = model.kinds.setdefault(kind, {})
        for r in pkg.get(kind, []):
            spec, need = handler.compile(r, model)
            table[r["id"]] = spec
            model.required += need
    return model
