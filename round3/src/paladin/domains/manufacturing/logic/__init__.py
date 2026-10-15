"""Manufacturing logic bindings: every IR ref (function / policy / constraint / precondition / outcome / payload)."""
from __future__ import annotations

from paladin.engine import LogicBindings
from paladin.opsrules import RuleSet

from . import actions, constraints, facts, functions, policies

# `read` helpers the ops spec names inside its business rules (spec/ops/manufacturing.json `helpers`)
READS = {"protecting_work_orders": lambda ctx, a: facts.protecting_work_orders(ctx.view, a["part"], a["source"], a["destination"])}


def _function_refs(node, out: dict) -> dict:
    """{implementation_ref: bound function} for every ref the IR declares (looked up by the name after ':')."""
    if isinstance(node, dict):
        ref = node.get("implementation_ref")
        if isinstance(ref, str):
            out[ref] = functions.BY_NAME[ref.rsplit(":", 1)[1]]
        for v in node.values():
            _function_refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _function_refs(v, out)
    return out


def build_bindings(ops_spec: dict, ir: dict) -> LogicBindings:
    rules = RuleSet(ops_spec, READS)
    b = LogicBindings()
    for kind, table in (("function", _function_refs(ir, {})), ("policy", policies.make(rules)),
                        ("constraint", constraints.make(rules)), ("precondition", actions.PRECONDITIONS),
                        ("outcome_predicate", actions.OUTCOMES), ("payload", actions.PAYLOADS)):
        for key, fn in table.items():
            b.bind(kind, key, fn)
    return b
