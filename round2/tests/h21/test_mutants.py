"""Mutation proof: every target mutant is killed by an assertion (not a crash); the clean build and a no-op patch stay clean."""
import pytest

from domains._pack import boot, load_ir
from domains.manufacturing.pack import build_pack as mfg_pack
from domains.project.pack import build_pack as prj_pack
from eoo_h21 import mutants


@pytest.fixture(scope="module")
def result():
    doms = {"manufacturing": {"ir": load_ir("manufacturing"), "engine": boot("manufacturing", mfg_pack())},
            "project": {"ir": load_ir("project"), "engine": boot("project", prj_pack())}}
    return mutants.run_all(doms, 400, 8)


def test_every_target_mutant_is_detected_and_controls_are_clean(result):
    assert result["controls"]["clean"] and result["controls"]["noop_patch"]["clean"] and result["controls"]["clean_build"]["clean"]
    by = {m["id"]: m for m in result["mutants"]}
    assert set(mutants.CONTRACT_FOUR) <= set(by) and len(by) == 7
    assert [k for k, m in by.items() if not m["killed_in_every_domain"]] == []


def test_each_mutant_is_caught_by_the_check_that_owns_it(result):
    by = {m["id"]: set(m["detected_by"]) for m in result["mutants"]}
    assert by["drop_property"] == by["drop_cardinality"] == by["function_generated_as_action"] == {"type_conformance"}
    assert by["expose_denied_action"] == by["suppress_allowed_action"] == by["delegation_flag_ignored"] == {"security_differential"}
    assert by["hardcode_concrete_interface_type"] == {"interface_polymorphism"}


def test_overexposure_and_underexposure_are_separated(result):
    by = {m["id"]: m["per_domain"] for m in result["mutants"]}
    assert all(r["differential_over"] > 0 and r["differential_under"] == 0 for r in by["expose_denied_action"].values())
    assert all(r["differential_under"] > 0 for r in by["suppress_allowed_action"].values())


def test_a_crashing_mutant_is_a_harness_error_never_a_kill():
    doms = {"project": {"ir": load_ir("project"), "engine": boot("project", prj_pack())}}

    def boom():
        raise RuntimeError("patch failed")
    saved = dict(mutants.TARGETS)
    mutants.TARGETS.clear()
    mutants.TARGETS["crashing"] = ("type-generation", boom)
    try:
        r = mutants.run_all(doms, 50, 1)
    finally:
        mutants.TARGETS.clear()
        mutants.TARGETS.update(saved)
    m = r["mutants"][0]
    assert m["harness_errors"] and m["killed_in_every_domain"] is False
