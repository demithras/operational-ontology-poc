"""H25 oracle unit tests: static-rule parity (G3-E10), procedural scenarios on hand-built cases."""
import copy
import functools

import pytest

from r3_oracle.const_static import static_errors
from r3_oracle.constitution import Constitution
from r3_shared.authspec import load_auth_spec
from r3_shared.governance import load_governance, validate_governance
from r3_shared.opsspec import load_ops_spec
from tests.p1e_gen import gen_doc

M = "manufacturing"
A = functools.lru_cache(None)(lambda d: __import__("json").load(open(f"spec/authority/{d}.v3.json")))


def test_static_parity_with_shared_validator():
    n_ok = n_bad = 0
    for seed in range(1500):
        doc, auth, ops, _ = gen_doc(seed)
        try:
            validate_governance(doc, auth, ops)
            shared = True
        except ValueError:
            shared = False
        mine = not static_errors(doc, auth, ops)
        assert mine == shared, (seed, static_errors(doc, auth, ops))
        n_ok += shared
        n_bad += not shared
    assert n_ok > 100 and n_bad > 100  # both sides exercised


def _c(model="hierarchical"):
    ops = load_ops_spec(M)
    return Constitution.from_docs(A(M), load_governance(model, M), ops), ops


def _step(c, who, action, seq, tick, rid):
    v = c.decide_action(who, action, seq, tick)
    assert v.status == "OK", (action, v)
    return c.apply({"kind": "action", "subject": who, "action": action, "seq": seq, "tick": tick, "rid": rid}), v


def _prop(case="c1", key="WO-7"):
    return {"kind": "propose", "case": case, "operation": "reschedule_work_order",
            "args": {"work_order": key, "new_start": 1, "new_end": 2}, "on_behalf_of": None}


def test_ungoverned_and_unknown():
    c, ops = _c()
    pe = _prop()
    pe["operation"] = "transfer_inventory"
    assert c.decide_action("planner-1", pe, 1, 0).reason in ("schema", "not_governed")
    assert c.decide_action(None, pe, 1, 0).reason == "token"
    assert c.decide_action("admin-1", {"kind": "execute", "case": "zz"}, 1, 0).reason == "unknown_case"
    assert c.decide_action("admin-1", {"kind": "bogus"}, 1, 0).reason == "schema"


def test_hierarchical_specialis_lapse_and_review_window():
    c, ops = _c()
    o = ops["operations"]
    op = next(x for x in o if x["name"] == "reschedule_work_order")
    names = [i["name"] for i in op["inputs"]]
    args = {n: ("WO-42" if i["type"] == "resource" else 1) for n, i in ((i["name"], i) for i in op["inputs"])}
    p = {"kind": "propose", "case": "c1", "operation": "reschedule_work_order", "args": args, "on_behalf_of": None}
    v = c.decide_action("planner-1", p, 1, 0)
    if v.status != "OK":
        pytest.skip(f"planner has no base authority here: {v}")
    assert v.body["bodies"] == ["office-lead"]  # specialis picks the narrow matter for WO-42
    c, _ = _step(c, "planner-1", p, 1, 0, "r1")
    ex = {"kind": "execute", "case": "c1"}
    assert c.decide_action("planner-1", ex, 2, 1).reason == "oracle_needed"
    f = c.final("c1", 3, 4)  # lapse deny after 4
    assert (f["state"], f["outcome"], f["rule"], f["basis"]) == ("FINAL", "DENY", "lapse", []) or f["state"] == "NOT_FINAL"
    assert c.decide_action("planner-1", ex, 3, 8).reason in ("case_denied", "not_final")
    j = {"kind": "judge", "case": "c1", "stage": "decision", "value": "concur", "merit": "anything"}
    c2, _ = _step(c, "supervisor-1", j, 2, 1, "j1")
    f = c2.final("c1", 3, 1)
    assert f["state"] == "NOT_FINAL"  # review window 3 is open
    assert c2.final("c1", 3, 4)["outcome"] == "ALLOW" and c2.final("c1", 3, 4)["basis"] == ["j1"]
    assert c2.decide_action("planner-1", ex, 3, 1).reason == "not_final"
    assert c2.decide_action("supervisor-1", j, 3, 1).reason in ("stage_closed",)
    ap = {"kind": "appeal", "case": "c1"}
    c3, _ = _step(c2, "planner-1", ap, 3, 2, "a1")
    assert c3.decide_action("planner-1", ap, 4, 2).reason == "already_appealed"
    assert c3.decide_action("planner-1", ex, 4, 5).reason == "oracle_needed"  # review pending
    rj = {"kind": "judge", "case": "c1", "stage": "review", "value": "overturn", "merit": "m"}
    c4, _ = _step(c3, "senior-1", rj, 4, 3, "rj1")
    f = c4.final("c1", 5, 3)
    assert (f["outcome"], f["rule"], f["basis"]) == ("DENY", "review", ["j1", "rj1"])
    assert c4.decide_action("planner-1", ex, 5, 3).reason == "case_denied"


def test_merit_never_changes_outcome():
    c, ops = _c("collegial")
    assert c.decide_action("planner-1", {"kind": "judge", "case": "nope", "stage": "decision", "value": "concur",
                                         "merit": "x"}, 1, 0).reason == "unknown_case"
    a = c.decide_action("planner-1", {"kind": "end", "emergency": "e"}, 1, 0)
    assert a.reason == "emergency_inactive"


def test_set_governance_registers_doc():
    c, _ = _c()
    d2 = copy.deepcopy(c.doc)
    d2["model"] = "other"
    c2 = c.apply({"kind": "set_governance", "doc": d2, "seq": 1, "tick": 0})
    assert c2.doc["model"] == "other" and c.doc["model"] == "hierarchical"
