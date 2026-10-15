"""PROT-H28 s9: each KNOWN["H28"] mutant, built at its real site, is killed by its OWN class on a scripted corpus while the clean
build scores 0 on that class (kill rule: own class > 0 AND clean == 0; exact failing request ids, not counts).
Class definitions are computed here from the EXTERNAL LEDGER and hand-derived intents only, never from the variant."""
import json

import pytest

from g4_adapters import Broadening, FalseFailure, FalseSuccess, Honest, TargetSubstitution
from g4_rig import BIGFEE, EXP, G4Rig, PUB
from paladin.variant import ADAPTER_MODULES, PaladinVariant
from r3_shared.extadapter import payload_digest
from r3_shared.mutants import KNOWN

REQS = [("m1", EXP), ("m2", {"po_id": "PO-992", "expedite_fee": 7}), ("m3", {"po_id": "PO-992", "expedite_fee": 8})]


def corpus(tmp, adapter, mutants=()):
    r = G4Rig(tmp, adapter=adapter, mutants=mutants)
    try:
        for rid, args in REQS:
            assert r.call("planner-1", "expedite_purchase_order", args, rid).status == "OK"
        for _ in range(3):                                                         # the harness's dispatch points, inside the window
            r.dep.dispatch_pending()
        states = {o["request_id"]: o["state"] for rid, _ in REQS for o in r.settle(rid)}
        intended = {(f"{rid}#0", "po:PO-992", payload_digest(a)) for rid, a in REQS}
        rows = r.ledger()["effects"]
        outside = sorted(x["correlation"] for x in rows if (x["correlation"], x["target"], x["payload_digest"]) not in intended)
        false_ok = sorted(k for k, v in states.items() if v == "RECONCILED_SUCCESS" and not [x for x in rows if x["correlation"] == f"{k}#0"])
        dups = {k: len([x for x in rows if x["correlation"] == f"{k}#0"]) - 1 for k in states}
        return {"outside": outside, "false_ok": false_ok, "dup": sorted(k for k, n in dups.items() if n > 0), "states": states}
    finally:
        r.finish()


KILL = [("adapter_success_trusted", FalseSuccess, "false_ok", ["m1", "m2", "m3"]),
        ("observation_coupled", FalseSuccess, "false_ok", ["m1", "m2", "m3"]),
        ("credential_scope_broadened", Broadening, "outside", ["m1#0", "m2#0", "m3#0"]),
        ("idempotency_disabled", FalseFailure, "dup", ["m1", "m2", "m3"])]


@pytest.mark.parametrize("mutant,adapter,cls,ids", KILL)
def test_mutant_is_killed_by_its_own_class_and_the_clean_build_is_zero(tmp_path, mutant, adapter, cls, ids):
    clean, mut = corpus(tmp_path / "clean", adapter), corpus(tmp_path / "mut", adapter, [mutant])
    assert clean[cls] == [] and mut[cls] == ids, (clean, mut)
    others = {"outside", "false_ok", "dup"} - {cls}
    assert all(mut[o] == [] for o in others), mut   # no collateral class


@pytest.mark.parametrize("mutant", ["adapter_success_trusted", "observation_coupled", "credential_scope_broadened",
                                    "idempotency_disabled", "divergence_rewritten"])
def test_negative_an_honest_adapter_scores_zero_on_every_class_even_under_the_mutant(tmp_path, mutant):
    out = corpus(tmp_path, Honest, [mutant])
    assert out["outside"] == out["false_ok"] == out["dup"] == [] and set(out["states"].values()) == {"RECONCILED_SUCCESS"}


def test_divergence_rewritten_loses_the_target_mutation_detection(tmp_path):
    got = {}
    for name, mutants in (("clean", ()), ("mut", ["divergence_rewritten"])):
        r = G4Rig(tmp_path / name, adapter=TargetSubstitution, mutants=mutants)
        try:
            assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
            got[name] = r.settle("r1")[0]["state"]
        finally:
            r.finish()
    assert got == {"clean": "DIVERGED", "mut": "RECONCILED_FAILED"}              # attempted mutation, final state != DIVERGED


def test_divergence_rewritten_with_a_broad_cap_turns_a_substituted_write_into_success(tmp_path):
    r = G4Rig(tmp_path, adapter=Broadening, mutants=["divergence_rewritten", "credential_scope_broadened"])
    try:
        assert r.call("planner-1", "expedite_purchase_order", EXP, "r1").status == "OK"
        assert r.settle("r1")[0]["state"] == "RECONCILED_SUCCESS" and r.applied("r1#0")[0]["target"] == "po:PO-OTHER"
    finally:
        r.finish()


@pytest.mark.parametrize("domain,op,args,sub", [("manufacturing", "expedite_purchase_order", BIGFEE, "planner-1"),
                                                ("project", "publish_result", {**PUB, "visibility": "public"}, "researcher-1")])
def test_policy_gate_in_adapter_moves_the_rule_out_of_the_decision_plane(tmp_path, domain, op, args, sub):
    clean = G4Rig(tmp_path / "c", domain)
    mut = G4Rig(tmp_path / "m", domain, mutants=["policy_gate_in_adapter"])
    try:
        c, m = clean.call(sub, op, args, "p1"), mut.call(sub, op, args, "p1")
        assert (c.status, c.body["reason"]) == ("DENIED", "approval_required")        # oracle: the request needs an approval
        assert m.status == "OK"                                                        # oracle_denied_variant_ok (R28-11b)
        mut.dep.dispatch_pending()
        assert mut.ledger()["effects"] == [] and all(not rec.log for rec in mut.recorders.values())   # blocked by adapter-side code
    finally:
        clean.finish(), mut.finish()


def test_policy_gate_in_adapter_is_statically_visible_and_the_clean_build_is_not():
    assert "paladin.extgate_mut" in PaladinVariant(["policy_gate_in_adapter"]).adapter_modules
    assert "paladin.extgate_mut" not in PaladinVariant().adapter_modules and "paladin.extgate_mut" not in ADAPTER_MODULES
    from pathlib import Path
    src = Path(__file__).resolve().parents[2] / "src" / "paladin"
    rules = {r["id"] for o in json.load(open(Path(__file__).resolve().parents[2] / "spec/ops/manufacturing.json"))["operations"]
             for r in o["business_rules"]}
    mut_src = (src / "extgate_mut.py").read_text()
    assert "expedite-large-fee-needs-approval" in mut_src and "paladin.opsrules" in mut_src      # business-rule literal + rule engine
    for m in ADAPTER_MODULES:
        text = (src / (m.split(".", 1)[1] + ".py")).read_text()
        assert not [r for r in rules if r in text] and "opsrules" not in text and "authcompile" not in text, m


def test_every_h28_mutant_has_a_test_here():
    assert sorted(KNOWN["H28"]) == sorted(["adapter_success_trusted", "credential_scope_broadened", "policy_gate_in_adapter",
                                           "idempotency_disabled", "observation_coupled", "divergence_rewritten"])
    covered = {k[0] for k in KILL} | {"divergence_rewritten", "policy_gate_in_adapter"}
    assert covered == set(KNOWN["H28"])
