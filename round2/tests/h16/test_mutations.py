"""Mutation proof (contract python_hypothesis_role.mutation_proof): each registered mutant is killed, controls clean."""
import pytest

from eoo_h16.kernel import rev_snapshot
from eoo_h16.mutation_run import detect, registry, run_mutations


@pytest.fixture(scope="module")
def before():
    return rev_snapshot("r2-engine-core")


@pytest.fixture(scope="module")
def result(before):
    return run_mutations(before)


def test_all_registered_target_mutants_are_killed_with_the_expected_signal(result):
    s = result["summary"]
    assert s["target_total"] == 4 and s["target_killed"] == 4 and s["kill_rate"] == 1.0
    assert s["target_classes_present"] == ["domain_special_case", "new_primitive_kind"]
    assert all(m["killed"] for m in result["mutants"]), [m["id"] for m in result["mutants"] if not m["killed"]]


def test_controls_are_clean_before_and_after(result):
    assert result["controls"]["clean"] and result["controls"]["clean_after_restore"]
    assert not result["controls"]["control"]["any_signal"]


def test_static_and_dynamic_domain_mutants_are_caught_by_different_signals(result):
    by = {m["id"]: m["signals_fired"] for m in result["mutants"]}
    assert "audit_branch" in by["M1_static_domain_id_compare_in_registry"]
    assert by["M2_runtime_domain_branch_in_loader"] == ["rename_invariance_broken"]  # invisible to the static scan
    assert by["M3_new_dispatch_kind"] == ["kernel_new_kind"] and by["M4_new_schema_resource_array"] == ["kernel_new_kind"]


def test_a_noop_mutant_is_not_killed(before):
    """Known-negative for the harness: a mutant that changes nothing must not be reported as killed."""
    res = detect(before)
    assert not any(res["signals"].values())


def test_each_source_mutation_changes_exactly_the_files_it_names(before):
    from eoo_h16 import mutants as M
    for name, ov in M.src_mutations().items():
        assert len(ov) == 1
        (rel, text), = ov.items()
        assert text != (M.ROOT / rel).read_text() and compile(text, rel, "exec")


def test_expected_signal_per_mutant_is_registered(before):
    ids = [m["id"] for m in registry(before)]
    assert len(ids) == len(set(ids)) == 8 and sum(m["target"] for m in registry(before)) == 4
