"""Helpers shared by the H24 harness tests (hand-built authority documents and tiny scenarios)."""
import copy

from r3_harness.h23.corpus import load_specs
from r3_harness.h24.env import G2Env

OP = "expedite_purchase_order"
ARGS = {"po_id": "PO-991", "expedite_fee": 10}


def base_spec(depth=4):
    ops, auth1 = load_specs()["manufacturing"]
    spec = copy.deepcopy(auth1)
    spec.update({"spec": "r3-authority-2", "max_delegation_depth": depth, "capabilities": [], "revoked": []})
    spec["grants"].append({"id": "g-pl-exp", "effect": "allow", "principal": {"id": "planner-1"}, "resource": {"any": True},
                           "operation": OP, "delegable": True, "origin": "neutral-extension"})
    return spec


def edge(eid, issuer, child, parent=None, ops=(OP,), keys=None, exp=None, redel=True):
    return {"id": eid, "issuer": issuer, "child": child, "parent": parent, "issued_at": 0, "expires_at": exp,
            "redelegable": redel, "scope": {"operations": list(ops), "resources": [{"type": "PurchaseOrder", "keys": keys}]}}


def make_env(variant, tag="t"):
    ops, _ = load_specs()["manufacturing"]
    return G2Env(variant, "manufacturing", ops, base_spec(), tag)


def judged(env):
    out = env.judge()
    return {c["n"]: out["calls"][c["n"]] for c in env.calls}, out


def classes(env):
    calls, out = judged(env)
    return sorted({k for r in calls.values() for k in r["classes"]} - {"ok"} | set(out["case_classes"])), calls


def use(env, rid="u1", actor="junior-1", obo="planner-1", args=None):
    return env.request(actor, obo, OP, args or ARGS, rid)
