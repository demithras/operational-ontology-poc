"""Launcher refusals (G3-E31b / G4-E27): every dev/non-dev branch of evaluator.py (DEV_BRANCHES) has a matching launcher refusal here, and the
AST of evaluator.py proves the list is complete (no is_dev use outside refuse_unless_dev calls)."""
import ast
import argparse
from pathlib import Path

import pytest

from r3_harness.h29 import evalchecks as EC, evaluator, launch
from r3_harness.h29.svcset import SvcSet

SRC = Path(evaluator.__file__)


def args(**kw):
    d = dict(exp_id="exp-h29-001", sequences=5600, controls=600, boundary=200, dev_overrides=False, candidate_tag=None)
    d.update(kw)
    return argparse.Namespace(**d)


def env_for(sv):
    return {"R3_H29_SVC": str(sv.root), "R3_H29_WORKERS": "1"}


def test_refuses_size_overrides(tmp_path):
    with pytest.raises(launch.Refusal) as e:
        launch.guard(args(sequences=100), tmp_path, env={})
    assert e.value.branch == "size_overrides"
    with pytest.raises(launch.Refusal) as e:
        launch.guard(args(dev_overrides=True), tmp_path, env={})
    assert e.value.branch == "size_overrides"
    assert launch.guard(args(exp_id="exp-h29-x-dev-1", sequences=100), tmp_path, env={})          # dev ids may shrink, stamped
    assert EC.overrides_for(5600, 600, 200) == {}


@pytest.mark.parametrize("stopped", ["anchor", "ext", "auth"])
def test_refuses_service_presence(tmp_path, stopped):
    with pytest.raises(launch.Refusal) as e:
        launch.guard(args(), tmp_path, env={})                                                  # nothing configured at all
    assert e.value.branch == "service_presence"
    sv = SvcSet(1)
    try:
        a, x, u = sv.procs[0]
        {"anchor": a, "ext": x, "auth": u}[stopped].proc.kill()                                 # one service stopped
        with pytest.raises(launch.Refusal) as e:
            launch.guard(args(candidate_tag="HEAD"), tmp_path, env=env_for(sv))
        assert e.value.branch == "service_presence" and stopped in str(e.value)
    finally:
        sv.cleanup()


def test_refuses_candidate_tag(tmp_path):
    sv = SvcSet(1)
    try:
        with pytest.raises(launch.Refusal) as e:
            launch.guard(args(), tmp_path, env=env_for(sv))                                      # no tag
        assert e.value.branch == "candidate_tag"
        with pytest.raises(launch.Refusal) as e:
            launch.guard(args(candidate_tag="HEAD~1"), tmp_path, env=env_for(sv))               # HEAD != tag
        assert e.value.branch == "candidate_tag"
    finally:
        sv.cleanup()


def test_refuses_freeze_manifest(tmp_path, monkeypatch):
    sv = SvcSet(1)
    try:
        monkeypatch.setattr(EC, "manifest_state", lambda path=None: {"missing_from_freeze": ["src/r3_harness/h29/faults.py"], "missing_on_disk": [],
                                                                      "freeze_paths_missing_on_disk": []})
        monkeypatch.setattr(EC, "freeze_state", lambda path=None: ({}, {}))
        with pytest.raises(launch.Refusal) as e:
            launch.guard(args(candidate_tag="HEAD"), tmp_path, env=env_for(sv))
        assert e.value.branch == "freeze_manifest"
    finally:
        sv.cleanup()


def test_every_evaluator_dev_branch_has_a_launcher_refusal_and_a_test():
    tree = ast.parse(SRC.read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "refuse_unless_dev"]
    branches = {c.args[1].value for c in calls}
    assert branches == set(evaluator.DEV_BRANCHES)
    uses = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "is_dev"]
    in_calls = sum(1 for c in calls for a in c.args[:1] if isinstance(a, ast.Name) and a.id == "is_dev")
    params = [n for n in ast.walk(tree) if isinstance(n, ast.arg) and n.arg == "is_dev"]
    # is_dev may only be (a) a parameter, (b) first arg of refuse_unless_dev, (c) the evaluate_variant -> _verdict hand-over
    assert len(uses) <= in_calls + 4, [u.lineno for u in uses]
    launch_src = Path(launch.__file__).read_text()
    me = Path(__file__).read_text()
    for b in branches:
        assert f'Refusal("{b}"' in launch_src, b
        assert f"def test_refuses_{b}" in me, b


def test_refuses_reason_map(tmp_path, monkeypatch):
    """G5-E29(d): a missing reason map is a launcher refusal for a non-dev id (the evaluator marks the run invalid via refuse_unless_dev)."""
    from r3_harness.h29 import reasonmap
    monkeypatch.setattr(reasonmap, "DEFAULT_PATH", tmp_path / "absent.json")
    sv = SvcSet(1)
    try:
        with pytest.raises(launch.Refusal) as e:
            launch.guard(args(candidate_tag="HEAD"), tmp_path, env=env_for(sv))
        assert e.value.branch == "reason_map"
    finally:
        sv.cleanup()
    reasons: list = []
    assert evaluator.refuse_unless_dev(False, "reason_map", reasonmap.load() is None, "absent", reasons) and reasons
    assert not evaluator.refuse_unless_dev(True, "reason_map", True, "absent", [])
