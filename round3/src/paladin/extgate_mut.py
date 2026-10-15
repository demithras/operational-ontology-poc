"""MUTANT policy_gate_in_adapter (PROT-H28 s9, Q10). Loaded by name ONLY when the mutant is active (never part of a clean
build's import closure, see PaladinVariant.adapter_modules). Two halves:
  strip(ops_spec)  - the decision plane stops requiring approval for the named gating rules (the request commits OK);
  refuses(intent)  - adapter-side code re-implements the removed rule and refuses to submit (governance in the adapter).
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

from paladin.opsrules import RuleSet

RULES = ("expedite-large-fee-needs-approval", "publish-public-needs-approval")


def strip(ops_spec: dict) -> dict:
    out = copy.deepcopy(ops_spec)
    for o in out["operations"]:
        for r in o["business_rules"]:
            if r["id"] in RULES:
                r["when"] = {"lit": False}
    return out


def refuses(intent: dict, ops_spec: dict) -> bool:
    rs, ctx = RuleSet(ops_spec, {}), None
    for o in ops_spec["operations"]:
        if o["name"] != intent["action"]:
            continue
        for r in o["business_rules"]:
            if r["id"] in RULES:
                ctx = SimpleNamespace(inputs=intent["inputs"], principal=None, view=None)
                if rs.matches(ctx, o["name"], r["id"]):
                    return True
    return False
