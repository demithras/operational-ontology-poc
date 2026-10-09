"""Ops-spec operations whose effects are ALL `external` and that the domain IR does not describe yet (the H28 project overlay,
Q2) are compiled into IR actions + generic bindings from the ops-spec DATA: input table, preconditions (predicate AST), business
rules (deny / require_approval ASTs) and the external effect declaration. No operation, rule or domain name appears here.
Domain packs that already describe an operation win (nothing is synthesised for it).
"""
from __future__ import annotations

import copy

from paladin.opsrules import RuleSet

OUTCOME_TEXT = "outcome is judged by the external observer path (PROT-H28), never by the Engine adapter reply"
_PRIM = {"string": "string", "integer": "integer", "boolean": "boolean", "number": "number"}


def _type(i: dict):
    if i["type"] == "resource":
        return {"ref": i["resource_type"]}
    return _PRIM.get(i["type"], "string")


def missing_ops(ir: dict, ops_spec: dict) -> list[dict]:
    have = {a["id"] for a in ir["actions"]}
    return [o for o in ops_spec["operations"]
            if o["name"] not in have and o["effects"] and all(e["kind"] == "external" for e in o["effects"])]


def extend_ir(ir: dict, ops_spec: dict) -> dict:
    out, extra = copy.deepcopy(ir), missing_ops(ir, ops_spec)
    for o in extra:
        n = o["name"]
        pols = {"hard_deny": "deny", "needs_approval": "require_approval", "allow": "allow"}
        for k, dec in pols.items():
            out["policies"].append({"id": f"{n}_{k}", "decision": dec, "expression_ref": f"ops:{n}#{k}", "version": "v1"})
        out["actions"].append({
            "id": n, "inputs": [{"name": i["name"], "type": _type(i), "required": bool(i["required"])} for i in o["inputs"]],
            "authority_refs": [], "policy_refs": [f"policy:{n}_{k}" for k in pols],
            "preconditions": [p["description"] for p in o["preconditions"]],
            "effects": [{"target": e["adapter"], "operation": "external_call", "fields": [i["name"] for i in o["inputs"]]}
                        for e in o["effects"]],
            "idempotency": "required", "outcome_predicate": OUTCOME_TEXT, "compensation_action": None, "version": "v1"})
    return out


def bindings_for_missing(ir: dict, ops_spec: dict) -> dict:
    """{kind: {key: fn}} for the operations `extend_ir` synthesises (call with the ORIGINAL ir)."""
    rules, tables = RuleSet(ops_spec, {}), {"policy": {}, "precondition": {}, "outcome_predicate": {}}
    for o in missing_ops(ir, ops_spec):
        n, brs = o["name"], o["business_rules"]

        def deny(ctx, n=n, brs=brs):
            return any(rules.matches(ctx, n, r["id"]) for r in brs if r["decision"] == "deny")

        def gated(ctx, n=n, brs=brs):
            return any(rules.matches(ctx, n, r["id"]) for r in brs if r["decision"] == "require_approval")

        tables["policy"].update({f"ops:{n}#hard_deny": deny, f"ops:{n}#needs_approval": gated,
                                 f"ops:{n}#allow": lambda ctx, d=deny, g=gated: not d(ctx) and not g(ctx)})
        for p in o["preconditions"]:
            tables["precondition"][p["description"]] = lambda ctx, n=n, p=p: rules.eval_predicate(ctx, n, p["predicate"])
        tables["outcome_predicate"][OUTCOME_TEXT] = lambda ctx: None
    return tables
