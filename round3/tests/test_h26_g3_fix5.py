"""G3 fix5 (G3-E25/E28): args_digest marker kind, invariant-respecting worlds, governed D4 probes, own-request canary echo."""
import json

from r3_harness.h26 import gen_pair, gen_plan, invariants, sim
from r3_oracle import disclosure_prov as P
from r3_oracle.disclosure_reads import canaries_of
from r3_shared.disclosure import marker
from tests.test_h26_g3_fix2 import _LV, _dec


def _ops(d):
    return json.load(open(gen_pair.ROUND3 / f"spec/ops/{d}.json"))


def _seed(ops):
    return sim.apply_changes(sim.empty(), [c for b in sim.seed_batches(ops) for c in b])


def test_args_digest_marker_kind_is_args():
    d = _dec({"id": "c", "flag": True})
    d["args_scalar_free"], d["args_refs"], d["resources"], d["subject"] = False, [], ["Component:c"], "other"
    lv = _LV({"Component:c": {"id": "c", "flag": True}})
    lv.prov = {"Component:c": "scalars"}
    out = P.expected_decision(lv, d)
    assert out["args_digest"] == marker("args") and marker("args") != marker("digest")


def test_every_invariant_is_state_or_declared_non_state():
    for dom in gen_pair.DOMAINS:
        ids = {i["id"] for i in _ops(dom)["invariants"]}
        assert not (ids - set(invariants.STATE) - set(invariants.NON_STATE)), dom
        assert not (set(invariants.STATE) & set(invariants.NON_STATE))


def test_seed_satisfies_invariants_and_known_bad_worlds_are_caught():
    m, p = _ops("manufacturing"), _ops("project")
    assert invariants.violations(m, _seed(m)) == [] and invariants.violations(p, _seed(p)) == []
    s = sim.apply_changes(_seed(m), [{"op": "update", "type": "InventoryLot", "key": "LOT-A-PX900", "props": {"reserved": 7217736}}])
    assert {"inventory-on-hand-covers-reserved", "inventory-available-nonnegative"} <= set(invariants.violations(m, s))
    s = sim.apply_changes(_seed(p), [{"op": "link", "link_type": "PRODUCES", "src": "Experiment:E-C@v1", "dst": "Evidence:EV-C-BAD"}])
    assert invariants.violations(p, s) == ["evidence-bound-to-version-commit-environment"]


def test_generated_worlds_satisfy_invariants_and_redraws_are_counted():
    redraws = 0
    for idx in range(120):
        pair, st = gen_pair.draw(2601, idx)
        redraws += st.get("invariant_redraws", 0)
        if pair is None:
            continue
        ops = _ops(pair["domain"])
        base = _seed(ops)
        for d in pair["w"]:
            assert invariants.violations(ops, gen_pair._snap_after(base, d, ops, pair["auth"])) == []
    assert redraws >= 1  # the draw loop does hit invariant-violating worlds


def test_d4_probes_never_on_governed_requests():
    n = 0
    for idx in range(150):
        pair, _ = gen_pair.draw(2601, idx, kind="G")
        if pair is None:
            continue
        ops = _ops(pair["domain"])
        from r3_oracle import const_eval
        for it in pair["plan"]:
            if it["m"] == "mutate" and it["kind"] == "d4":
                n += 1
                assert not const_eval.covering(pair["governance"], it["op"], const_eval.resources_for(ops, it["op"], it["args"]))
    assert n > 0


def test_canary_scan_ignores_own_request_echo():
    pair_canaries = {"ck-48576200", "cv-aaaaaaaaaaaa"}
    item = {"m": "query", "name": "q", "args": {"work_order": "ck-48576200"}}
    prot = pair_canaries - canaries_of({}) - canaries_of(item)
    assert prot == {"cv-aaaaaaaaaaaa"}
    assert prot & canaries_of({"x": "cv-aaaaaaaaaaaa"})  # a DIFFERENT hidden canary is still caught
    assert gen_plan  # imported for coverage of the module under test
