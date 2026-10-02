"""Dispatch/lifecycle tracing, the frozen lifecycle oracle, and the mutation proof."""
import pytest

from eoo_exp.util import load_oracle
from eoo_h20 import mutants, payloads
from eoo_h20.trace import Tracer, profiling_dispatch

L = load_oracle("h20", "lifecycle")


def test_frozen_lifecycle_known_positive_and_negatives():
    ok = ["PROPOSED", "PENDING_APPROVAL", "APPROVED", "EXECUTING", "EFFECTS_COMMITTED", "RECONCILED_SUCCESS"]
    assert L.history_problem(ok) is None and L.history_problem(["PROPOSED", "DENIED"]) is None
    assert L.history_problem(["PROPOSED", "EXECUTING"]) and L.history_problem(["APPROVED"]) and L.history_problem(["PROPOSED", "DENIED", "APPROVED"])
    assert L.history_problem([]) and L.history_problem(["PROPOSED", "OUTCOME_UNKNOWN"])
    assert L.dispatch_problem("actions", "propose") is None and L.dispatch_problem("actions", "teleport") and L.dispatch_problem("zones", "get")


def test_oracle_lifecycle_equals_the_engine_transition_table():
    """Cross-check of two independently written tables (the oracle is transcribed from the docs, the engine from code)."""
    from eoo_engine.pipeline import TRANSITIONS
    eng = {k: {x for x in v if x != k} for k, v in TRANSITIONS.items() if k}
    assert eng == {k: set(v) for k, v in L.NEXT.items()}


def test_tracer_records_dispatch_executions_and_provenance_per_package():
    from eoo_h17.drivers import new_driver
    from eoo_h17.scenarios import ALL
    t = Tracer()
    with t.installed():
        scn = next(s for s in ALL["manufacturing"] if s.id == "m_ok_planner")
        d = new_driver("manufacturing", "std")
        rec = d.engine.propose(scn.action, scn.inputs, scn.principal, idempotency_key="t1")
        d.engine.call_function("available_quantity", {"lot": "LOT-A-PX900"})
    assert rec["state"] == "RECONCILED_SUCCESS"
    pkg = "manufacturing-ontology"
    assert t.dispatch[(pkg, "actions", "propose")] == 1 and t.dispatch[(pkg, "functions", "call")] >= 1 and t.dispatch[(pkg, "authority_rules", "decide")] == 1
    row = next(iter(t.execs.values()))
    assert row["history"][0] == "PROPOSED" and row["history"][-1] == "RECONCILED_SUCCESS" and L.history_problem(row["history"]) is None
    assert all(f in row["prov_keys"] for f in L.PROVENANCE_REQUIRED_FIELDS)
    assert all(len(v) == 1 for v in t.handler_ids.values())


def test_tracer_leaves_the_engine_untouched_after_exit():
    from eoo_engine import DISPATCH_TABLE
    from eoo_engine.engine import Engine
    before = (dict(DISPATCH_TABLE["actions"].ops), Engine.record)
    t = Tracer()
    with t.installed():
        assert DISPATCH_TABLE["actions"].ops["propose"] is not before[0]["propose"]
    assert (dict(DISPATCH_TABLE["actions"].ops), Engine.record) == before


def test_payload_marks_a_nonconforming_history_and_a_foreign_dispatch_op():
    t = Tracer()
    t.dispatch[("manufacturing-ontology", "actions", "teleport")] = 1
    t.execs[(1, "x1")] = {"pkg": "manufacturing-ontology", "action": "transfer_inventory", "history": ["PROPOSED", "EXECUTING"], "gates": []}
    p = payloads.dispatch_traces(t, {}, {})["domains"]["manufacturing"]
    assert p["dispatch_outside_generic_set"] == ["actions.teleport"] and p["executions"]["nonconforming_count"] == 1
    assert p["actions"]["executed_with_conformant_history"] == []


def test_profile_hook_attributes_files_to_dispatch():
    from eoo_h17.drivers import new_driver
    from eoo_h17.scenarios import ALL
    t = Tracer()
    with t.installed(), profiling_dispatch(t):
        scn = next(s for s in ALL["manufacturing"] if s.id == "m_ok_planner")
        new_driver("manufacturing", "std").engine.propose(scn.action, scn.inputs, scn.principal, idempotency_key="p1")
    names = {f.rsplit("/", 1)[-1] for f in t.dispatch_files}
    assert {"pipeline.py", "authority.py", "gates.py"} <= names and "wms_fake.py" in names  # the adapter ran inside dispatch too


@pytest.fixture(scope="module")
def mut():
    return mutants.run_all(40)


def test_every_target_mutant_is_detected_and_controls_are_clean(mut):
    assert mut["controls"]["clean"]
    assert [m["id"] for m in mut["mutants"] if not m["detected"]] == [] and all(m["target"] for m in mut["mutants"])
    assert {m["class"] for m in mut["mutants"]} == {"domain_branch_in_engine", "governance_in_adapter"} and len(mut["mutants"]) >= 6


def test_engine_mutants_are_caught_by_both_independent_signals(mut):
    for m in (x for x in mut["mutants"] if x["class"] == "domain_branch_in_engine"):
        assert m["signals"]["static_flagged"] and m["signals"]["dynamic_flagged"], m["id"]
    e3 = next(m for m in mut["mutants"] if m["id"] == "E3_identity_prefix_branch")
    assert e3["signals"]["token_hits"] == 0 and e3["signals"]["identity_branch_hits"] >= 1  # no domain token in the source


def test_the_vocabulary_audit_misses_an_innocuous_name_and_the_probe_does_not(mut):
    a = next(m for m in mut["mutants"] if m["id"] == "A1b_unnamed_policy_in_wms_adapter")
    assert a["static_blind_spot"] and a["detected_by"] == ["ok_mode_adapter_probe"]


def test_a_noop_edit_is_not_flagged(mut):
    n = mut["controls"]["noop_edit"]
    assert not n["static_flagged"] and not n["dynamic_flagged"]


def test_mutations_never_touch_the_repository():
    from eoo_exp.util import git
    assert git("status", "--porcelain", "--", "round2/src/eoo_engine", "round2/domains").strip() == ""
