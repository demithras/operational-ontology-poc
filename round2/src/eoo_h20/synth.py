"""Generated synthetic definitions (object type + Function + governed Action [+ policy/authority/constraint]) using only
existing resource kinds, and their IR package / bindings. Nothing here knows a real domain id.

A *definition* is a JSON-able dict: ids, the Function kind, the Action's shape and one scenario to execute against it.
"""
from __future__ import annotations

import hypothesis.strategies as st

from eoo_engine import LogicBindings

EFFECTS = ("create", "update", "external", "link", "update+external")
APPROVER = "syn_approver"
ACTOR = "syn_actor"


@st.composite
def definitions(draw) -> dict:
    i = draw(st.integers(0, 99999))
    effect = draw(st.sampled_from(EFFECTS))
    action = {
        "effect": effect, "idempotency": draw(st.sampled_from(["required", "not_applicable"])),
        "precondition": draw(st.sampled_from(["none", "none", "positive"])),
        "policy": draw(st.sampled_from(["none", "allow", "approval", "deny", "classify"])),
        "policy_t": draw(st.integers(0, 40)),
        "constraint": draw(st.sampled_from(["none", "hard", "soft"])), "cap": draw(st.integers(5, 60)),
        "authority": draw(st.sampled_from(["role", "relation"])) if effect != "create" else "role"}
    scenario = {
        "principal": draw(st.sampled_from(["actor"] * 8 + ["roleonly", "relonly", "outsider", "ghost"])),
        "key": draw(st.sampled_from(["present"] * 6 + ["missing"])),
        "ref": draw(st.sampled_from(["new"] * 5 + ["dup"] if effect == "create" else ["good"] * 5 + ["bad"])),
        "n": draw(st.integers(-3, 80)),
        "approval": draw(st.sampled_from(["approve", "approve", "reject", "self", "unauthorized"])),
        "adapter": draw(st.sampled_from(["confirm", "confirm", "fail", "silent", "raise"])),
        "retry": draw(st.booleans())}
    fn = {"kind": draw(st.sampled_from(["get_n", "plus", "zero"])), "k": draw(st.integers(0, 9))}
    return {"i": i, "fn": fn, "action": action, "scenario": scenario}


ALIAS: dict = {}  # id slot -> replacement (alias-invariance probe: give synthetic resources REAL domain identifiers)


def ids(d: dict) -> dict:
    i = d["i"]
    base = {"pkg": f"syn-pkg-{i}", "dom": f"syn-dom-{i}", "T": f"SynT{i}", "S": f"SynS{i}", "L": f"SynL{i}",
            "fn": f"syn_fn_{i}", "act": f"syn_act_{i}", "pol": f"syn_pol_{i}", "obs": f"SynObs{i}", "actor": ACTOR,
            "approver": APPROVER}
    return {k: ALIAS.get(k, v) for k, v in base.items()}


def _p(name, typ, required=True):
    return {"name": name, "type": typ, "required": required, "immutable": False}


def package(d: dict) -> dict:
    n, a = ids(d), d["action"]
    eff = a["effect"]
    inputs, effects = [], []
    if eff == "create":
        inputs = [{"name": "key", "type": "string"}, {"name": "n", "type": "integer"}]
        effects = [{"target": n["T"], "operation": "create", "fields": ["key", "n"]}]
    else:
        inputs = [{"name": "box", "type": {"ref": n["T"]}}, {"name": "n", "type": "integer"}]
        if eff in ("update", "update+external"):
            effects.append({"target": n["T"], "operation": "update", "fields": ["n"]})
        if eff in ("external", "update+external"):
            effects.append({"target": "SynSys", "operation": "external_call", "fields": ["box"]})
        if eff == "link":
            inputs += [{"name": "shelf", "type": {"ref": n["S"]}}]
            effects = [{"target": n["L"], "operation": "link"}]
    capability = f"action:{n['act']}"
    prin = "role:" + n["actor"] if a["authority"] == "role" else f"{n['T']}#owner"
    rules = [{"id": "r-act", "principal_selector": prin, "capability": capability, "resource_selector": f"{n['T']}:*",
              "effect": "allow"}]
    refs = ["auth:r-act"]
    if a["policy"] == "approval":
        rules.append({"id": "r-appr", "principal_selector": "role:" + n["approver"], "capability": f"approval:{n['act']}",
                      "resource_selector": "*", "effect": "allow"})
        refs.append("auth:r-appr")
    pols = [] if a["policy"] == "none" else [{"id": n["pol"], "decision": {"allow": "allow", "approval": "require_approval",
                                              "deny": "deny", "classify": "classify"}[a["policy"]],
                                              "expression_ref": "expr:pol", "version": "pv1"}]
    cons = [] if a["constraint"] == "none" else [{"id": "c-cap", "scope": n["T"], "expression_ref": "expr:cap",
                                                   "severity": a["constraint"]}]
    return {
        "package_id": n["pkg"], "domain_id": n["dom"], "version": "s1",
        "object_types": [{"id": n["T"], "primary_key": "key", "implements": [],
                          "properties": [_p("key", "string"), _p("n", "integer")]},
                         {"id": n["S"], "primary_key": "key", "implements": [], "properties": [_p("key", "string")]}],
        "link_types": [{"id": n["L"], "from": n["T"], "to": n["S"], "from_cardinality": {"min": 0, "max": 1},
                        "to_cardinality": {"min": 0, "max": 1}}],
        "interfaces": [],
        "functions": [{"id": n["fn"], "inputs": [{"name": "box", "type": {"ref": n["T"]}}], "output": "integer",
                       "purity": "NO_COMMITTED_BUSINESS_SIDE_EFFECT", "reads": [n["T"] + ".n"],
                       "implementation_ref": "impl:fn"}],
        "actions": [{"id": n["act"], "inputs": inputs, "authority_refs": refs,
                     "policy_refs": [] if not pols else ["policy:" + n["pol"]],
                     "preconditions": [] if a["precondition"] == "none" else ["n is positive"], "effects": effects,
                     "idempotency": a["idempotency"], "outcome_predicate": "outcome", "version": "a1"}],
        "policies": pols, "authority_rules": rules,
        "observation_types": [{"id": n["obs"], "subject_type": n["T"], "source_binding": "syn-feed",
                               "truth_status": "observed", "properties": [_p("state", "string")]}],
        "constraints": cons}


def bindings(d: dict) -> LogicBindings:
    n, a, f = ids(d), d["action"], d["fn"]
    t = a["policy_t"]

    def fn(view, args):
        if f["kind"] == "zero":
            return 0
        v = view.get(n["T"], args["box"])["props"]["n"]
        return v + f["k"] if f["kind"] == "plus" else v

    def outcome(ctx):
        if a["effect"] not in ("external", "update+external"):
            return True
        states = [o["data"]["state"] for o in ctx.observations]
        return True if "OK" in states else (False if "BAD" in states else None)
    return LogicBindings({
        "function": {"impl:fn": fn}, "policy": {"expr:pol": lambda ctx: ctx.inputs["n"] > t},
        "precondition": {"n is positive": lambda ctx: ctx.inputs["n"] > 0},
        "constraint": {"expr:cap": lambda ctx: all(o["props"]["n"] <= a["cap"] for o in ctx.view.list(n["T"]))},
        "outcome_predicate": {"outcome": outcome}})


class SynSys:
    """External system double: confirm | fail | silent | raise. It decides nothing: it answers and observes."""

    def __init__(self, mode: str, obs: str):
        self.mode, self.obs, self.calls, self._obs = mode, obs, 0, []

    def apply(self, effect, payload):
        self.calls += 1
        if self.mode == "raise":
            raise ConnectionError("synthetic system unreachable")
        if self.mode in ("confirm", "fail"):
            self._obs.append({"observation_type": self.obs, "execution": effect["execution"],
                              "data": {"state": "OK" if self.mode == "confirm" else "BAD"}})
        return {"accepted": True, "ticket": effect["effect_id"]}

    def observations(self):
        return list(self._obs)


def generate(seed: int, n: int) -> list:
    """``n`` definitions drawn by Hypothesis under a fixed seed (duplicates possible; callers de-duplicate by sha)."""
    from hypothesis import HealthCheck, Phase, given, seed as hseed, settings
    out: list = []

    @settings(max_examples=n, database=None, deadline=None, suppress_health_check=list(HealthCheck), phases=(Phase.generate,))
    @hseed(seed)
    @given(definitions())
    def collect(d):
        out.append(d)
    collect()
    return out
