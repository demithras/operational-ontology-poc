"""Generic evaluator of ops-spec business-rule expressions (spec/ops/<domain>.json ``operations[].business_rules[].when``).

The rules are DATA read at boot: relations (``actor_holds``), thresholds (``lit``) and field comparisons come from the
spec the deployment was booted with, never from per-domain code. Domain packs contribute only (a) the ``read`` helpers
named by the spec (``helpers``: {name: fn(ctx, args)}) and (b) the object-type lookup that the spec's own input table
already carries. Pure and read-only: it looks at ``ctx.view`` / ``ctx.principal`` and the supplied argument map.
"""
from __future__ import annotations

from typing import Any, Callable

Helper = Callable[[Any, dict], Any]
_ORDER = {"gt": lambda a, b: a > b, "ge": lambda a, b: a >= b, "lt": lambda a, b: a < b, "le": lambda a, b: a <= b}


def holds(principal, obj_type: str, key: Any, relation: str) -> bool:
    # a delegated request acts with its delegation chain (agent on behalf of P): any link may hold the relation
    return any((obj_type, key, relation) in p.relations for p in principal.chain())


class RuleSet:
    """Business rules of one booted ops spec, evaluated against a Paladin logic context."""

    def __init__(self, ops_spec: dict, helpers: dict[str, Helper] | None = None):
        self._ops = {o["name"]: o for o in ops_spec["operations"]}
        self._helpers = dict(helpers or {})

    def rule(self, op: str, rule_id: str) -> dict:
        for r in self._ops[op]["business_rules"]:
            if r["id"] == rule_id:
                return r
        raise KeyError(f"no business rule {rule_id!r} in operation {op!r}")

    def gating_rule(self, op: str) -> str:
        """Id of the business rule the spec says makes ``op`` need an approval (operations[].approval.required_when_rule)."""
        return self._ops[op]["approval"]["required_when_rule"]

    def matches(self, ctx, op: str, rule_id: str, args: dict | None = None) -> bool:
        """True when the spec rule's ``when`` holds; ``args`` defaults to the request inputs."""
        return self._eval(self.rule(op, rule_id)["when"], self._ops[op], ctx, ctx.inputs if args is None else args) is True

    def _input_type(self, op: dict, name: str) -> str | None:
        return next((i.get("resource_type") for i in op["inputs"] if i["name"] == name), None)

    def _eval(self, n: Any, op: dict, ctx, args: dict) -> Any:
        if "input" in n:
            return args.get(n["input"])
        if "lit" in n:
            return n["lit"]
        if "field" in n:
            ref = n["field"][0]
            t = self._input_type(op, ref["input"]) if "input" in ref else None
            row = ctx.view.get(t, self._eval(ref, op, ctx, args)) if t else None
            return None if row is None else row["props"].get(n["field"][1])
        if "read" in n:
            sub = {k: self._eval(v, op, ctx, args) for k, v in n["args"].items()}
            return self._helpers[n["read"]](ctx, sub)
        return self._pred(n, op, ctx, args)

    def _pred(self, n: dict, op: dict, ctx, args: dict) -> Any:
        k = n["op"]
        if k == "actor_holds":
            ref = n["on"]
            return holds(ctx.principal, self._input_type(op, ref["input"]), self._eval(ref, op, ctx, args), n["relation"])
        a = [self._eval(x, op, ctx, args) for x in n.get("args", [])]
        if k == "and":
            return all(x is True for x in a)
        if k == "or":
            return any(x is True for x in a)
        if k == "not":
            return a[0] is not True
        if k == "eq":
            return a[0] == a[1]
        if k == "ne":
            return a[0] != a[1]
        if k == "in":
            return a[0] in a[1]
        if k in _ORDER:
            ok = all(isinstance(x, int) and not isinstance(x, bool) for x in a)
            return ok and _ORDER[k](a[0], a[1])
        raise ValueError(f"unsupported ops-spec operator {k!r}")
