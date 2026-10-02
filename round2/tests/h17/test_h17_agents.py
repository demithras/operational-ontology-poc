"""Agent adversary: raw-write attempts are refused; record-tampering attacks are measured with controls; baseline contextual."""
import pytest

from eoo_h17 import agents, baseline, tamper
from eoo_h17.agents import run_attack
from eoo_h17.drivers import new_driver

DOMAINS = ("manufacturing", "project")


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("name,fn", agents.RAW_ATTACKS, ids=[n for n, _ in agents.RAW_ATTACKS])
def test_raw_write_attacks_are_refused(domain, name, fn):
    r = run_attack(new_driver(domain, "std"), name, "raw_write", fn)
    assert not r["violation"] and not r["unexpected_exception"] and not r["world_changed"], r


def test_reachability_walker_known_negative_flags_a_tool_that_exposes_the_store():
    from eoo_engine.capabilities import ReadOnly
    drv = new_driver("manufacturing", "std")
    leaky = ReadOnly(view=ReadOnly(store=drv.engine.store), request=lambda *a: None)
    n, hits = agents._walk(leaky)
    assert hits and "store" in hits[0]
    n2, hits2 = agents._walk(drv.engine.tool("agent-1"))
    assert hits2 == [] and n2 >= 2


def test_surface_check_known_negative_flags_an_extra_capability():
    drv = new_driver("manufacturing", "std")
    real = drv.engine.tool
    from eoo_engine.capabilities import ReadOnly

    def leaky(pid):
        t = real(pid)
        return ReadOnly(request=t.request, call_function=t.call_function, propose_action=t.propose_action, view=t.view,
                        approve=lambda *a: None)
    drv.engine.tool = leaky
    assert agents.a_surface(drv)["violation"] is True
    assert agents.a_surface(new_driver("manufacturing", "std"))["violation"] is False


@pytest.mark.parametrize("domain", DOMAINS)
def test_tamper_controls_produce_no_unexpected_effect(domain):
    plan = [x for x in tamper.TAMPER_BOTH + (tamper.TAMPER_MFG if domain == "manufacturing" else []) if x[0].startswith("control")]
    assert plan
    for n, f in plan:
        r = run_attack(new_driver(domain, "std"), n, "tamper", f)
        assert not r["violation"], r


def test_tampered_returned_record_cannot_execute_an_effect_the_gates_denied():
    """MEASUREMENT. Engine v1 (exp-h17-001): every row below was a violation (editing the live record returned by
    tool.propose_action defeated the gates). Engine v1.1 returns read-only snapshots: the edit itself is refused with
    CapabilityError and nothing executes. Adapted for v1.1 (P5c); the v1 finding stays recorded in exp-h17-001."""
    out = {}
    for d in DOMAINS:
        plan = tamper.TAMPER_BOTH + (tamper.TAMPER_MFG if d == "manufacturing" else [])
        for n, f in plan:
            if not n.startswith("control"):
                r = run_attack(new_driver(d, "std"), n, "tamper", f)
                out[(d, n)] = (r["violation"], r["world_changed"], r["exception"])
    assert len(out) == 4 and set(out.values()) == {(False, False, "CapabilityError")}, out


def test_tamper_attack_is_what_causes_the_effect_not_the_scenario():
    d = new_driver("project", "std")
    assert run_attack(d, "c", "tamper", tamper.t_state_flip_control)["world_changed"] is False
    d = new_driver("project", "std")
    # Engine v1 (exp-h17-001): True. Engine v1.1: the tamper is refused, so the world stays unchanged (P5c).
    assert run_attack(d, "a", "tamper", tamper.t_state_flip_recover)["world_changed"] is False


def test_baseline_single_operation_model_loses_to_the_metadata_attacks():
    rows = {r["attack"]: r for r in baseline.attacks()}
    assert rows["unknown_raw_write_operation"]["violation"] is False and rows["unauthorized_effectful_operation"]["violation"] is False
    assert rows["read_labelled_operation_that_writes"]["violation"] is True and rows["effect_flag_flipped_by_registrant"]["violation"] is True
