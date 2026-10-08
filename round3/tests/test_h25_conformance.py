"""CONFORMANCE FIRST (Gate 2 lesson): generated edge cases run against BOTH real variants through the registry and are
compared with the oracle's observable decisions (ORACLE-AND-HARNESS-G3 section C, C25-1..C25-5). The real variants may not
be built yet: then those parametrisations SKIP with a stated reason (that is information, not green). `fake-honest`
proves the test machinery itself (an oracle-backed reference must pass every item)."""
import copy
import random

import pytest

from r3_harness.h25 import audit, plays_a, plays_b
from r3_harness.h25.env import G3Env
from r3_harness.h25.gen_case import Case, run_case
from r3_harness.h25.gen_model import make_instance
from r3_oracle.const_static import static_errors
from r3_shared import constitutional as K
from r3_shared.registry import load_variant
from tests.h25_util import fake
from tests.p1e_gen import gen_doc

VARIANTS = ["fake-honest", "paladin", "conventional"]
CLEAN = {"ok", "race_refusal_ok"}


def get(name):
    if name.startswith("fake-"):
        return fake(name)
    try:
        return load_variant(name)
    except NotImplementedError as exc:
        pytest.skip(f"variant {name} not implemented yet - G3 ({exc})")


def _dirty(r):
    return sorted(set(r["classes"]) | set(r["case_classes"]) - CLEAN) if (set(r["classes"]) | set(r["case_classes"])) - CLEAN else []


# -- C25-1: schema edge cases ---------------------------------------------------------------------------------------
def _mutations(rng):
    base = [{"kind": "propose", "case": "c1", "operation": "x", "args": {}, "on_behalf_of": None},
            {"kind": "judge", "case": "c1", "stage": "decision", "value": "concur", "merit": "m"},
            {"kind": "judge", "case": "c1", "stage": "review", "value": "uphold", "merit": "m"},
            {"kind": "appeal", "case": "c1"}, {"kind": "execute", "case": "c1"},
            {"kind": "act", "emergency": "e", "operation": "x", "args": {}}, {"kind": "end", "emergency": "e"}]
    out = []
    for a in base:
        out.append(a)
        k = rng.choice([x for x in a if x != "kind"] or ["case"])
        b = copy.deepcopy(a)
        del b[k]
        out.append(b)                                              # missing key
        out.append({**a, "extra": 1})                              # additional property
        c = copy.deepcopy(a)
        c[k] = rng.choice([7, None, [], True, {"x": 1}])
        out.append(c)                                              # wrong type
        if a["kind"] == "judge":
            out.append({**a, "value": "uphold" if a["stage"] == "decision" else "concur"})  # value of the other stage
            out.append({**a, "stage": "nope"})
    out += [{"kind": "bogus"}, {}, {"kind": 5}, [], "execute"]
    return out


@pytest.mark.parametrize("name", VARIANTS)
def test_c25_1_schema_edge_cases(name):
    v = get(name)
    inst = make_instance("collegial", "manufacturing", 1)
    env = G3Env(v, "manufacturing", inst["ops"], inst["auth"], inst["doc"], "c251")
    try:
        who = inst["auth"]["principals"][0]["id"]
        bad = []
        for n, a in enumerate(_mutations(random.Random(7))):
            res = env.dep.constitutional(env.token(who), a, f"s{n}")
            is_schema = res.status == "INVALID" and res.body.get("reason") == "schema"
            if is_schema != (K.check_action(a) is not None):
                bad.append((a, res.status, res.body))
        assert not bad, bad[:5]
    finally:
        env.close()


# -- C25-2 / C25-3: check order (>= 2 failing checks) and exact governance marks -------------------------------------------
class _OrderCase(Case):
    def script(self):
        plays_a.decision_play(self)
        plays_a.decision_play(self)
        for _ in range(5):
            plays_b.order_fuzz(self)
        plays_b.noise_play(self)


@pytest.mark.parametrize("name", VARIANTS)
def test_c25_2_3_check_order_and_marks(name):
    v = get(name)
    bad, committed = [], 0
    for i in range(60):
        r = _OrderCase(v, 11, i, tag="order").run()
        committed += sum(1 for x in r["calls"] if x.get("committed") and x.get("kind") == "constitutional")
        if _dirty(r):
            bad.append((r["id"], _dirty(r)))
    assert committed > 100  # marks were actually compared
    assert not bad, bad[:5]


@pytest.mark.parametrize("name", VARIANTS)
def test_c25_corpus_slice_has_no_mismatch(name):
    v = get(name)
    bad = [(i, _dirty(r)) for i in range(40) if _dirty(r := run_case(v, 12, i))]
    assert not bad, bad[:5]


# -- C25-4: generated governance documents: shared validator == oracle == variant ------------------------------------------
@pytest.mark.parametrize("name", VARIANTS)
def test_c25_4_documents(name):
    v = get(name)
    mism = []
    for seed in range(120):
        doc, _auth, _ops, _names = gen_doc(seed)
        inst = make_instance("collegial", doc["domain"], 1)
        env = G3Env(v, doc["domain"], inst["ops"], inst["auth"], inst["doc"], "c254")
        try:
            rec = env.set_governance(doc)
            oracle_invalid = bool(static_errors(doc, inst["auth"], inst["ops"]))
            if rec["raised"] != oracle_invalid:
                mism.append((seed, rec["status"], rec["reason"], oracle_invalid))
        finally:
            env.close()
    assert not mism, mism[:5]


# -- C25-5: renaming checker --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", VARIANTS)
def test_c25_5_renaming_invariance(name):
    v = get(name)
    keep = ("admin",) if name.startswith("fake-") else ()
    r = audit.rename_audit(v, 21, 40, keep_roles=keep)
    assert r["domain_branch"] == 0, r["first"]


def test_c25_5_flags_the_mutant_build():
    r = audit.rename_audit(fake("fake-domainbranch"), 21, 80, domain="project", keep_roles=("admin",))
    assert r["domain_branch"] > 0
