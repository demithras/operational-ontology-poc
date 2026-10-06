"""Property test (Hypothesis): over random hostile call sequences, every committed world effect is justified by an
INDEPENDENT authority oracle (frozen effective-authority rule over the neutral auth spec; imports r3_shared only).
The same property is killed by each effect-visible H23 mutant (shrunk counterexample), and the surface audit kills
tool_overexposure.
"""
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, Phase, example, given, settings
from hypothesis import strategies as st

from paladin_rig import Rig
from r3_shared.authspec import allowed_operations

PRINCIPALS = ["planner-1", "junior-1", "supervisor-1", "senior-1", "nobody-1", "admin-1", "agent-1", "agent-hostile-1", "agent-orphan"]
OBO = [None, None, "planner-1", "supervisor-1", "nobody-1", "admin-1"]
WH = ["WH-A", "WH-B", "WH-C", "WH-X"]
OPS = {
    "transfer_inventory": st.fixed_dictionaries({"source_warehouse": st.sampled_from(WH), "destination_warehouse": st.sampled_from(WH),
                                                  "part": st.sampled_from(["PX-17", "PX-900", "PX-NOPE"]),
                                                  "quantity": st.sampled_from([1, 5, 60, 90, 400, -3, "x"])}),
    "expedite_purchase_order": st.fixed_dictionaries({"po_id": st.sampled_from(["PO-991", "PO-992", "PO-0"]),
                                                      "expedite_fee": st.sampled_from([0, 10, 900, -1])}),
    "reschedule_work_order": st.fixed_dictionaries({"work_order_id": st.sampled_from(["WO-42", "WO-43", "WO-0"]),
                                                    "new_planned_start": st.sampled_from([5, 55])}),
}
IDENT = st.sampled_from([None, None, None, ("principal", "planner-1"), ("actor", "admin-1"), ("requested_by", "planner-1")])


def _match_op(pat, op):
    return pat == op or pat == "*" or (pat.endswith(":*") and op.startswith(pat[:-1]))


def _psel(sel, p, res):
    if sel.get("any"):
        return True
    if "role" in sel:
        return sel["role"] in p["roles"]
    if "id" in sel:
        return sel["id"] == p["id"]
    held = {(r["type"], r["key"], r["relation"]) for r in p["relations"]}
    bound = [r for r in res if r[0] == sel["on_type"]]
    return bool(bound) and all((t, k, sel["relation"]) in held for t, k in bound)


def oracle_allows(auth, sub, obo, op, resources):
    """Frozen effective-authority rule (authority part only; business rules are the executor's)."""
    P = {p["id"]: p for p in auth["principals"]}

    def own(pid, need_delegable):
        p = P[pid]
        ok = False
        for g in auth["grants"]:
            if not _match_op(g["operation"], op) or g["operation"].startswith(("write:", "update:")):
                continue
            rs = g["resource"]
            if not (rs.get("any") or any(t == rs.get("type") for t, _ in resources)):
                continue
            if _psel(g["principal"], p, resources):
                if g["effect"] == "deny":
                    return False
                ok = ok or (g["delegable"] or not need_delegable)
        return ok
    if sub not in P:
        return False
    if obo is None:
        return own(sub, False)
    if obo not in P or op not in {o for d in auth["delegations"] if (d["agent"], d["on_behalf_of"]) == (sub, obo) for o in d["operations"]}:
        return False
    return own(sub, True) and own(obo, False) and not any(  # (d) deny on subject or P
        g["effect"] == "deny" and _match_op(g["operation"], op) and _psel(g["principal"], P[w], resources)
        for w in (sub, obo) for g in auth["grants"])


def resources_of(rig, op, args):
    spec = next(o for o in rig.ops["operations"] if o["name"] == op)
    return [(i["resource_type"], args[i["name"]]) for i in spec["inputs"] if i["type"] == "resource" and i["name"] in args]


step = st.tuples(st.sampled_from(PRINCIPALS), st.sampled_from(sorted(OPS)), st.data(), st.sampled_from(OBO),
                 st.sampled_from(["tool", "direct"]), st.sampled_from(["a", "b", "c"]), IDENT)


def run(rig, steps):
    committed: dict = {}
    for who, op, data, obo, via, rid, ident in steps:
        args = data.draw(OPS[op])
        sent = dict(args)
        if ident:
            sent[ident[0]] = ident[1]
        f = rig.dep.call_tool if via == "tool" else rig.dep.direct
        res, eff = rig.effects_of(lambda: f(rig.token(who), op, sent, on_behalf_of=obo, request_id=f"rid-{rid}"))
        if eff:
            assert res.status == "OK", (who, op, sent, res)
            assert oracle_allows(rig.auth, who, obo, op, resources_of(rig, op, args)), ("FORBIDDEN EFFECT", who, obo, op, sent, eff)
            assert f"rid-{rid}" not in committed, ("second effect for a committed request id", rid, eff)
            committed[f"rid-{rid}"] = (who, obo, op, args)
        if res.status == "OK" and not eff and "replayed" in res.body:
            assert f"rid-{rid}" in committed
    return committed


def surface_audit(rig):
    """(principal, listed tools, upper bound): the bound is the shared static authority view, evaluated as-itself
    (PROT-H23) plus the delegations' operations reachable through each delegator."""
    import copy
    ops = [o["name"] for o in rig.ops["operations"]]
    itself = copy.deepcopy(rig.auth)
    for p in itself["principals"]:
        p["delegated_by"] = None
    for p in rig.auth["principals"]:
        bound = set(allowed_operations(itself, p["id"], ops))
        for d in rig.auth["delegations"]:
            if d["agent"] == p["id"]:
                bound |= set(allowed_operations(itself, d["on_behalf_of"], ops)) & set(d["operations"])
        yield p["id"], {t.name for t in rig.dep.tools(rig.token(p["id"]))}, bound


class _Fixed:  # a st.data() stand-in with a fixed argument dict
    def __init__(self, args):
        self.args = args

    def draw(self, _strategy):
        return dict(self.args)


B = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
A = {"source_warehouse": "WH-A", "destination_warehouse": "WH-B", "part": "PX-17", "quantity": 5}
# minimal hand-written counterexamples for each mutant (Hypothesis explores around them and finds others itself)
EXAMPLES = {
    "identity_substitution": [("agent-hostile-1", "transfer_inventory", _Fixed(B), None, "direct", "a", ("principal", "planner-1"))],
    "backstop_bypass": [("agent-hostile-1", "transfer_inventory", _Fixed(A), "planner-1", "direct", "a", None)],
    "mutable_gated_input": [("agent-hostile-1", "transfer_inventory", _Fixed(B), "planner-1", "direct", "a", None),
                            ("agent-hostile-1", "transfer_inventory", _Fixed(A), "planner-1", "direct", "a", None)],
}


def make(mutants=()):
    return Rig(Path(tempfile.mkdtemp()), "manufacturing", mutants=mutants)


SETTINGS = dict(max_examples=60, deadline=None, derandomize=True, suppress_health_check=list(HealthCheck))


@settings(**SETTINGS)
@given(st.lists(step, min_size=1, max_size=8))
def test_clean_paladin_has_no_forbidden_effect(steps):
    run(make(), steps)


@pytest.mark.parametrize("mutant", ["identity_substitution", "backstop_bypass", "mutable_gated_input"])
def test_effect_visible_mutants_are_killed_by_the_property(mutant):
    seen = {"runs": 0}

    @example(EXAMPLES[mutant])
    @settings(**{**SETTINGS, "max_examples": 200, "phases": [Phase.explicit, Phase.generate]})  # no shrink: keeps it fast
    @given(st.lists(step, min_size=1, max_size=6))
    def prop(steps):
        seen["runs"] += 1
        run(make((mutant,)), steps)
    with pytest.raises(AssertionError) as exc:
        prop()
    assert "FORBIDDEN EFFECT" in str(exc.value) or "second effect" in str(exc.value), exc.value
    print(f"{mutant}: killed after {seen['runs']} generated sequence(s)")


def test_tool_overexposure_is_killed_by_the_surface_audit_not_by_effects():
    assert all(listed <= bound for _p, listed, bound in surface_audit(make()))
    mut = make(("tool_overexposure",))
    assert any(not listed <= bound for _p, listed, bound in surface_audit(mut))  # the audit sees it ...
    probe = _Fixed({"source_warehouse": "WH-A", "destination_warehouse": "WH-B", "part": "PX-17", "quantity": 5})
    run(mut, [("nobody-1", "transfer_inventory", probe, None, "tool", "a", None),
              ("nobody-1", "transfer_inventory", probe, None, "direct", "b", None)])  # ... the effect meter does not (no assertion)
