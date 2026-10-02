"""The state machine: clean on the real Engine, every required sequence class reachable, known-negative caught."""
import pytest

from eoo_h17 import mutants
from eoo_h17.machine import CLASSES, Mismatch, O, make_machine
from eoo_h17.runlib import new_sink, run_machine, unique

DOMAINS = ("manufacturing", "project")


def test_generated_sequences_agree_with_the_oracle_on_both_domains():
    for i, d in enumerate(DOMAINS):
        sink = run_machine(d, 100 + i, 150)
        assert sink["failures"] == [], sink["failures"][-1:]
        assert unique(sink) > 60
        seen = {c for r in sink["records"] for c in r["classes"]}
        need = set(CLASSES) - ({"approve", "deny"} if d == "project" else set())
        assert need <= seen, need - seen


def test_the_machine_oracle_is_the_independent_oracle_file():
    assert O.__name__.startswith("oracles_h17_model")
    assert O.World.__module__.startswith("oracles_h17_model")


def _machine(domain, profile_pick=0):
    m = make_machine(domain, {"records": [], "failures": []})()
    m.setup(profile_pick)
    return m


@pytest.mark.parametrize("domain", DOMAINS)
@pytest.mark.parametrize("point", ["PROPOSED", "APPROVED", "EXECUTING", "ext_intent", "ext_response", "EFFECTS_COMMITTED"])
def test_every_crash_point_recovers_exactly_once(domain, point):
    m = _machine(domain)
    ppick = O.CRASH_POINTS.index(point)
    ok_pick = next(i for i in range(50) if m._pick(i, "ok", "approval", "unauthorized", "invalid").kind == "ok"
                   and not m._pick(i, "ok", "approval", "unauthorized", "invalid").clock)
    m.crash_restart(ok_pick, ppick)
    assert m.orc.classes()[-1] == O.INFLIGHT
    m.execute()
    m.execute()  # recovery twice: still exactly once
    assert m.orc.marker()[1] == m.orc.marker()[2] == m.drv.marker()["effect_log"]


@pytest.mark.parametrize("domain", DOMAINS)
def test_retry_never_adds_effects(domain):
    m = _machine(domain)
    m.propose(0, False)
    before = m.drv.marker()
    m.retry(0, False)
    m.retry(0, True)
    assert m.drv.marker() == before


def test_unapproved_execution_is_refused():
    m = _machine("manufacturing")
    m.propose_for_approval(0, False)
    before = m.drv.marker()
    m.force_execute(0)
    m.approve(0, True)  # a bad approver
    assert m.drv.marker() == before and m.orc.classes() == [O.PENDING]
    m.approve(0, False)
    assert m.orc.classes() == [O.DONE] and m.drv.marker()["effect_log"] == 1


def test_known_negative_function_write_mutant_is_caught_by_the_machine():
    sink = new_sink()
    with mutants.function_writes_effect_log():
        run_machine("manufacturing", 7, 60, sink=sink)
    assert sink["failures"] and sink["failures"][-1]["kind"] == "function_effect"
    assert sink["failures"][-1]["steps"][-1][0] == "function_call"  # shrunk to the offending call


def test_known_negative_gate_bypass_mutant_is_caught_by_the_machine():
    sink = new_sink()
    with mutants.bypass_authority_gate():
        run_machine("manufacturing", 7, 100, sink=sink)
    assert sink["failures"] and sink["failures"][-1]["kind"] in mutants.GATE_EXPECT


def test_mismatch_carries_a_kind():
    with pytest.raises(Mismatch) as e:
        raise Mismatch("effect_log", "x")
    assert e.value.kind == "effect_log"
