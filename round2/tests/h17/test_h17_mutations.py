"""Registered mutants: each target mutant is killed by its expected signal with a shrunk counterexample; controls are clean."""
import pytest

from eoo_h17 import mutants


def test_all_registered_target_mutants_are_killed_with_the_expected_signal():
    rows = [mutants.run_mutant(r, 5, 120) for r in mutants.REGISTRY]
    assert {r["class"] for r in rows if r["target"]} == {"function_write", "gate_bypass"}
    for r in rows:
        assert r["killed"] and r["killed_by_expected_signal"], (r["id"], r["counterexample"] and r["counterexample"]["kind"])
        c = r["counterexample"]
        assert c["steps"][0][0] == "init" and 1 <= c["n_steps"] <= 4, (r["id"], c["steps"])  # shrunk


def test_controls_are_clean_before_and_after():
    before = mutants.control(5, 60)
    with mutants.bypass_authority_gate():
        pass
    after = mutants.control(5, 60)
    assert before["clean"] and after["clean"], (before, after)


def test_mutation_patches_are_removed_after_use():
    from eoo_engine import authority, gates
    from eoo_engine.registry import DISPATCH_TABLE
    o = (authority.evaluate, gates.run_logic_gate, gates.evaluate_policies, DISPATCH_TABLE["functions"].ops["call"])
    for _, _, _, ctx, _ in mutants.REGISTRY:
        with ctx():
            pass
    assert o == (authority.evaluate, gates.run_logic_gate, gates.evaluate_policies, DISPATCH_TABLE["functions"].ops["call"])


def test_a_mutant_that_changes_nothing_would_survive():
    """Known-negative for the kill logic: a no-op patch is NOT reported as killed."""
    import contextlib
    row = ("M0_noop", "gate_bypass", True, contextlib.nullcontext, mutants.GATE_EXPECT)
    r = mutants.run_mutant(row, 5, 60)
    assert r["killed"] is False and r["counterexample"] is None
