"""The independent oracle: pure transitions, explicit gate tokens, static independence from the Engine."""
import ast
from pathlib import Path

import pytest

from eoo_exp.util import ROOT, load_oracle

O = load_oracle("h17", "model")
OK = {"identity": True, "request": True, "inputs": True, "fresh": True, "authority": True, "preconditions": True, "policy": "allow"}


def req(key="k", n=1, **tok):
    return O.Req("a", f"i-{key}", key, {**OK, **tok}, n)


def test_oracle_does_not_import_the_engine_or_domains():
    tree = ast.parse((ROOT / "oracles/h17/model.py").read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree)
                                                                              if isinstance(n, ast.Import) for a in n.names}
    assert not {m for m in mods if m and m.split(".")[0] in ("eoo_engine", "eoo_toolchain", "domains", "eoo_exp", "eoo_h17")}, mods
    assert mods <= {"dataclasses"}


def test_oracle_import_checker_catches_a_planted_import():
    """Known-negative for the checker above: the same scan flags a module that imports the Engine."""
    tree = ast.parse("from eoo_engine import Engine\nimport domains.project\n")
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {a.name for n in ast.walk(tree)
                                                                              if isinstance(n, ast.Import) for a in n.names}
    assert {m.split(".")[0] for m in mods} == {"eoo_engine", "domains"}


def test_read_transitions_never_change_the_world():
    w = O.World()
    w.propose(req("a"))
    before = (w.marker(), w.classes())
    w.read()
    w.function_call()
    w.force_execute(0)
    assert (w.marker(), w.classes()) == before


@pytest.mark.parametrize("gate", ["identity", "request", "inputs", "fresh", "authority", "preconditions"])
def test_a_missing_gate_token_denies_with_zero_effects(gate):
    w = O.World()
    w.propose(req(**{gate: False}))
    assert w.marker() == (0, 0, 0) and w.classes() == [O.DENIED] and w.execs[0].denied_at == gate


def test_policy_deny_zero_effects_allow_effects_approval_pending():
    w = O.World()
    w.propose(req("d", policy="deny"))
    w.propose(req("p", policy="approval"))
    assert w.marker() == (0, 0, 0) and w.classes() == [O.DENIED, O.PENDING]
    w.propose(req("ok", n=3))
    assert w.marker() == (0, 3, 3)


def test_approval_needs_an_authorised_approver_and_only_once():
    w = O.World()
    w.propose(req(policy="approval"))
    w.approve(0, False)
    w.reject(0, False)
    assert w.marker() == (0, 0, 0) and w.classes() == [O.PENDING]
    w.approve(0, True)
    w.approve(0, True)
    assert w.marker() == (0, 1, 1) and w.classes() == [O.DONE]


def test_retry_is_idempotent_and_key_reuse_with_a_different_intent_is_denied():
    w = O.World()
    a = w.propose(req("k"))
    assert w.propose(req("k")) == a and w.marker() == (0, 1, 1) and len(w.execs) == 1
    w.propose(O.Req("a", "other", "k", dict(OK), 1))
    assert w.marker() == (0, 1, 1) and w.classes() == [O.DONE, O.DENIED] and w.execs[1].denied_at == "idempotency"


@pytest.mark.parametrize("point,mid,final,fclass", [
    ("PROPOSED", (0, 0, 0), (0, 2, 2), O.DONE), ("APPROVED", (0, 0, 0), (0, 2, 2), O.DONE), ("EXECUTING", (0, 0, 0), (0, 2, 2), O.DONE),
    ("ext_intent", (0, 0, 0), (0, 0, 0), O.UNKNOWN), ("ext_response", (0, 0, 1), (0, 2, 2), O.DONE),
    ("EFFECTS_COMMITTED", (0, 2, 2), (0, 2, 2), O.DONE)])
def test_crash_points_then_recovery(point, mid, final, fclass):
    w = O.World()
    w.propose(req(n=2), crash=point)
    assert w.marker() == mid and w.classes() == [O.INFLIGHT]
    w.recover()
    assert w.marker() == final and w.classes() == [fclass]
    w.recover()
    assert w.marker() == final  # recovery is idempotent


def test_crash_at_proposed_with_a_failing_gate_stays_effect_free():
    w = O.World()
    w.propose(req(authority=False), crash="PROPOSED")
    w.recover()
    assert w.marker() == (0, 0, 0) and w.classes() == [O.DENIED]


def test_adapter_faults_and_outcome_observation():
    w = O.World()
    w.set_mode("timeout")
    w.propose(req("t"))
    assert w.marker() == (0, 0, 0) and w.classes() == [O.UNKNOWN]
    w.observe_outcome(0)
    assert w.classes() == [O.UNKNOWN]  # nothing happened externally: stays unknown, never fabricated success
    w.set_mode("commit_no_response")
    w.propose(req("c"))
    assert w.marker() == (0, 0, 1) and w.classes() == [O.UNKNOWN, O.UNKNOWN]
    w.observe_outcome(1)
    assert w.marker() == (0, 0, 1) and w.classes() == [O.UNKNOWN, O.DONE]  # reconciling classifies, never re-executes


def test_a_response_already_received_is_not_lost_when_the_adapter_later_times_out():
    w = O.World()
    w.propose(req(n=1), crash="ext_response")
    w.set_mode("timeout")
    w.recover()
    assert w.marker() == (0, 1, 1) and w.classes() == [O.DONE]
