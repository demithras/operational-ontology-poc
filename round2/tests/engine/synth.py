"""Synthetic, domain-free IR package + test logic + fake adapter for engine lifecycle tests."""
from __future__ import annotations

import itertools

from eoo_engine import AdapterRegistry, Engine, LogicBindings, Principal


def _p(name, typ, required=True, immutable=False):
    return {"name": name, "type": typ, "required": required, "immutable": immutable}


def package() -> dict:
    return {
        "package_id": "synthetic-boxes", "version": "s1",
        "object_types": [
            {"id": "Box", "primary_key": "key", "implements": ["Labeled"],
             "properties": [_p("key", "string", immutable=True), _p("level", "integer"),
                            _p("label", {"optional": "string"}, required=False)]},
            {"id": "Shelf", "primary_key": "key", "implements": ["Labeled"], "properties": [_p("key", "string")]},
        ],
        "link_types": [{"id": "BoxOnShelf", "from": "Box", "to": "Shelf", "from_cardinality": {"min": 0, "max": 1},
                        "to_cardinality": {"min": 0, "max": 2}}],
        "interfaces": [{"id": "Labeled", "required_properties": [_p("key", "string")], "required_links": [],
                        "capabilities": ["read"]}],
        "functions": [{"id": "box_level", "inputs": [{"name": "box", "type": {"ref": "Box"}}], "output": "integer",
                       "purity": "NO_COMMITTED_BUSINESS_SIDE_EFFECT", "reads": ["Box.level"],
                       "implementation_ref": "impl:box_level"}],
        "actions": [
            {"id": "fill_box", "inputs": [{"name": "box", "type": {"ref": "Box"}}, {"name": "amount", "type": "integer"}],
             "authority_refs": ["auth:filler", "auth:approver", "auth:blocked", "auth:keeper-delegable",
                                "auth:keeper-strict"],
             "policy_refs": ["policy:p-deny", "policy:p-approval", "policy:p-allow", "policy:p-classify"],
             "preconditions": ["amount is positive"], "effects": [{"target": "Box", "operation": "update",
                                                                    "fields": ["level"]}],
             "idempotency": "required", "outcome_predicate": "box level reflects the fill", "version": "a1"},
            {"id": "ship_box", "inputs": [{"name": "box", "type": {"ref": "Box"}}],
             "authority_refs": ["auth:filler-ship"], "policy_refs": [], "preconditions": [],
             "effects": [{"target": "Carrier", "operation": "external_call", "fields": ["box"]}],
             "idempotency": "required", "outcome_predicate": "carrier confirms delivery", "version": "a1"},
            {"id": "make_box", "inputs": [{"name": "key", "type": "string"}, {"name": "level", "type": "integer"}],
             "authority_refs": ["auth:maker"], "policy_refs": [], "preconditions": [],
             "effects": [{"target": "Box", "operation": "create", "fields": ["key", "level"]}],
             "idempotency": "not_applicable", "outcome_predicate": "box exists", "version": "a1"},
            {"id": "shelve_box", "inputs": [{"name": "box", "type": {"ref": "Box"}},
                                            {"name": "shelf", "type": {"ref": "Shelf"}}],
             "authority_refs": ["auth:maker"], "policy_refs": [], "preconditions": [],
             "effects": [{"target": "BoxOnShelf", "operation": "link"}],
             "idempotency": "not_applicable", "outcome_predicate": "box exists", "version": "a1"},
        ],
        "policies": [{"id": "p-deny", "decision": "deny", "expression_ref": "expr:deny", "version": "pv1"},
                     {"id": "p-approval", "decision": "require_approval", "expression_ref": "expr:approval",
                      "version": "pv1"},
                     {"id": "p-allow", "decision": "allow", "expression_ref": "expr:allow", "version": "pv2"},
                     {"id": "p-classify", "decision": "classify", "expression_ref": "expr:classify", "version": "pv1"}],
        "authority_rules": [
            {"id": "filler", "principal_selector": "role:filler", "capability": "action:fill_box",
             "resource_selector": "Box:*", "effect": "allow"},
            {"id": "approver", "principal_selector": "role:approver", "capability": "approval:big_fill",
             "resource_selector": "Box:*", "effect": "allow"},
            {"id": "blocked", "principal_selector": "role:blocked", "capability": "action:*",
             "resource_selector": "*", "effect": "deny"},
            {"id": "keeper-delegable", "principal_selector": "box#keeper", "capability": "action:fill_box",
             "resource_selector": "*", "effect": "allow", "delegation_allowed": True},
            {"id": "keeper-strict", "principal_selector": "box#owner", "capability": "action:fill_box",
             "resource_selector": "*", "effect": "allow", "delegation_allowed": False},
            {"id": "filler-ship", "principal_selector": "role:filler", "capability": "action:ship_box",
             "resource_selector": "Box:*", "effect": "allow"},
            {"id": "maker", "principal_selector": "role:filler", "capability": "action:*", "resource_selector": "*",
             "effect": "allow"},
        ],
        "observation_types": [{"id": "CarrierObserved", "subject_type": "Box", "source_binding": "carrier-feed",
                               "truth_status": "observed", "properties": [_p("state", "string")]}],
        "constraints": [{"id": "level-cap", "scope": "Box", "expression_ref": "expr:cap", "severity": "hard"},
                        {"id": "level-soft", "scope": "Box", "expression_ref": "expr:soft", "severity": "soft"},
                        {"id": "ship-only", "scope": "ship_box", "expression_ref": "expr:never", "severity": "hard"}],
    }


class FakeCarrier:
    """External system double. ``mode``: confirm | fail | silent | raise."""

    def __init__(self, mode: str = "confirm"):
        self.mode, self.calls, self._obs = mode, [], []

    def apply(self, effect, payload):
        self.calls.append((dict(effect), dict(payload)))
        if self.mode == "raise":
            raise ConnectionError("carrier unreachable")
        if self.mode in ("confirm", "fail"):
            self._obs.append({"observation_type": "CarrierObserved", "execution": effect["execution"],
                              "data": {"state": "DELIVERED" if self.mode == "confirm" else "LOST"}})
        return {"accepted": True, "ticket": effect["effect_id"]}

    def emit(self, execution: str, state: str, otype: str = "CarrierObserved") -> None:
        self._obs.append({"observation_type": otype, "execution": execution, "data": {"state": state}})

    def observations(self):
        return list(self._obs)


def knobs() -> dict:
    return {"deny": False, "approval_over": 50, "allow": True, "classify": True, "cap": 100, "soft": 50,
            "precondition": None, "ship_constraint": True, "outcome": None}


def bindings(k: dict) -> LogicBindings:
    def level_after(ctx):
        for p in ctx.planned:
            if p["operation"] == "update":
                return p["payload"]["level"]
        return None

    def box_level(view, args):
        return view.get("Box", args["box"])["props"]["level"]

    def cap(ctx):
        return all(o["props"]["level"] <= k["cap"] for o in ctx.view.list("Box"))

    def soft(ctx):
        return all(o["props"]["level"] <= k["soft"] for o in ctx.view.list("Box"))

    def fill_payload(ctx):
        cur = ctx.call("box_level", {"box": ctx.inputs["box"]})
        return {"$key": ctx.inputs["box"], "level": cur + ctx.inputs["amount"]}

    def fill_outcome(ctx):
        if k["outcome"] is not None:
            return k["outcome"]
        rec = ctx.view.get("Box", ctx.inputs["box"])
        return rec is not None and rec["ver"] > 1

    def carrier(ctx):
        states = [o["data"]["state"] for o in ctx.observations]
        if "DELIVERED" in states:
            return True
        return False if "LOST" in states else None

    return LogicBindings({
        "function": {"impl:box_level": box_level},
        "policy": {"expr:deny": lambda ctx: k["deny"], "expr:approval": lambda ctx: ctx.inputs["amount"] > k["approval_over"],
                   "expr:allow": lambda ctx: k["allow"], "expr:classify": lambda ctx: k["classify"]},
        "precondition": {"amount is positive": lambda ctx: k["precondition"] if k["precondition"] is not None
                         else ctx.inputs["amount"] > 0},
        "constraint": {"expr:cap": cap, "expr:soft": soft, "expr:never": lambda ctx: k["ship_constraint"]},
        "outcome_predicate": {"box level reflects the fill": fill_outcome, "carrier confirms delivery": carrier,
                              "box exists": lambda ctx: True},
        "payload": {"fill_box#0": fill_payload},
    })


class Clock:
    def __init__(self):
        self._n = itertools.count()

    def __call__(self) -> str:
        return f"t{next(self._n):06d}"


PRINCIPALS = {
    "filler": Principal("filler", {"filler"}),
    "filler2": Principal("filler2", {"filler"}),
    "approver": Principal("approver", {"approver"}),
    "blocked": Principal("blocked", {"filler", "blocked"}),
    "nobody": Principal("nobody", set()),
    "keeper": Principal("keeper", set(), {("Box", "b1", "keeper"), ("Box", "b1", "owner")}),
}


def build(k=None, carrier=None, journal=None, faults=(), seed=True, register=True, clock=None):
    k = k if k is not None else knobs()
    carrier = carrier if carrier is not None else FakeCarrier()
    eng = Engine(package(), bindings(k), AdapterRegistry({("external_call", "Carrier"): carrier}), journal=journal,
                 clock=clock or Clock(), faults=faults)
    if register:
        for p in PRINCIPALS.values():
            eng.register_principal(p)
        rel = {("Box", "b1", "keeper"), ("Box", "b1", "owner")}
        eng.register_principal(Principal("agent", set(), rel, PRINCIPALS["keeper"]))
        eng.register_principal(Principal("rogue-agent", set(), rel, PRINCIPALS["nobody"]))
    if seed:
        eng.seed([{"op": "create", "type": "Box", "key": "b1", "props": {"key": "b1", "level": 10}},
                  {"op": "create", "type": "Box", "key": "b2", "props": {"key": "b2", "level": 0}},
                  {"op": "create", "type": "Shelf", "key": "s1", "props": {"key": "s1"}}])
    return eng, k, carrier


def effects_of(eng, xid: str) -> tuple:
    return eng.effect_log.where(execution=xid)
