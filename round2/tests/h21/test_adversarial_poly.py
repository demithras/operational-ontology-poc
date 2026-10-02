"""Adversarial agent calls to hidden capabilities (0 effects, absent tools) and interface polymorphism without per-type code."""
import pytest

from domains._pack import boot
from domains.manufacturing.pack import build_pack as mfg_pack
from domains.project.pack import build_pack as prj_pack
from eoo_h21 import adversarial, mutants, polymorphism, run
from eoo_toolchain.runtime import EngineClient, UnknownTool

SETUP = {"manufacturing": (mfg_pack, lambda: run.MFG_NOW), "project": (prj_pack, lambda: None)}


def boot_domain(dom):
    pack = SETUP[dom][0]()
    clock = SETUP[dom][1]()
    return boot(dom, pack, clock=(lambda: clock) if clock else None), pack


@pytest.mark.parametrize("dom", ["manufacturing", "project"])
def test_hidden_actions_are_absent_and_calls_have_no_effect(built, dom):
    ir, _d, _i, _sdk, _c, surf = built[dom]
    eng, pack = boot_domain(dom)
    pid, tries = run.POSITIVE[dom]
    r = adversarial.run(dom, ir, surf, eng, pack[1], 5, 60, tries, pid)
    t = r["totals"]
    assert t["hidden_action_instances"] > 10 and t["unknown_tool"] == t["direct_calls"] + t["fuzz_calls"] and t["other_outcomes"] == 0
    assert t["principals_with_effects"] == 0 and t["engine_touched_by_surface_attacks"] == 0 and t["attribute_leaks"] == 0
    assert t["backstop_calls"] == t["backstop_denied"] > 0 and t["surface_oracle_tool_mismatches"] == 0
    assert r["positive_control"]["effect_observed"] is True  # the effect meter can see a real effect


def test_effect_meter_known_negative_sees_a_forced_effect(built):
    """If a hidden action were reachable, the meter would show it: force the Engine path with an ALLOWED principal."""
    ir, _d, _i, _sdk, _c, surf = built["project"]
    eng, pack = boot_domain("project")
    before = adversarial.meter(eng, pack[1])
    EngineClient(eng).propose("create_hypothesis", {"claim": "forced"}, "researcher-1", "forced-1")
    assert adversarial.meter(eng, pack[1]) != before


def test_hidden_tool_is_absent_not_refused(built):
    ir, _d, _i, _sdk, _c, surf = built["project"]
    eng, _p = boot_domain("project")
    c = EngineClient(eng)
    viewer = surf.AgentSurface(c, c.principal_plain("viewer-1"), c.world([o["id"] for o in ir["object_types"]]), adversarial.engine_check.real_opaque(eng))
    assert not any(t.startswith("act_") for t in viewer.tools) and not hasattr(viewer, "act_create_hypothesis")
    with pytest.raises(UnknownTool):
        viewer.call("act_create_hypothesis", claim="x")
    with pytest.raises(UnknownTool):
        viewer.call(None)


@pytest.mark.parametrize("dom", ["manufacturing", "project"])
def test_one_generic_interface_tool_serves_every_implementer(built, dom):
    ir, _d, _i, _sdk, _c, surf = built[dom]
    eng, _p = boot_domain(dom)
    rows = polymorphism.against_engine(ir, surf, eng)
    named = {"manufacturing": ("Statused", 4), "project": ("VersionedResearchObject", 6)}[dom]
    row = next(r for r in rows if r["interface"] == named[0])
    assert row["implementer_count"] == named[1] and row["types_served"] == named[1] and row["equals_store"]
    assert all(r["equals_store"] and r["tool_source_names_an_implementer"] == [] for r in rows)
    for r in rows:
        after = polymorphism.after_adding_types(ir, r["interface"], r["tool_source"])
        assert after["tool_source_identical"] and after["serves_new_types"]


def test_hardcoded_interface_type_mutant_is_visible_in_the_source_and_the_results(built):
    ir, *_ = built["project"]
    eng, _p = boot_domain("project")
    with mutants.patched(*mutants.m_hardcode_interface()):
        r = mutants.evaluate_surface(ir, eng, [])
    assert r["polymorphism_failures"] == ["VersionedResearchObject", "GitBound"][:len(r["polymorphism_failures"])] and r["polymorphism_failures"]
