"""G4 fix6: the launcher refuses a non-dev run whose adapter catalogue is not frozen (or differs) in FREEZE_G4, before any evidence is written."""
import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

from r3_harness.h28 import evaluator

R3 = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_h28_mod", R3 / "scripts" / "run_h28.py")
run_h28 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_h28)
REL = evaluator.CATALOGUE_REL
CUR = evaluator.catalogue_state()[1]


def _args(exp_id):
    return argparse.Namespace(exp_id=exp_id, cases=5600, controls=1000, dev_overrides=False, candidate_tag="r3-x")


@pytest.fixture
def env(monkeypatch):
    """Every other non-dev precondition passes; only the freeze content varies."""
    monkeypatch.setattr(run_h28, "require_external", lambda _id: None)
    monkeypatch.setenv("R3_ANCHOR_SOCK", "s")
    monkeypatch.setenv("R3_ANCHOR_DIR", "d")
    monkeypatch.setattr(run_h28, "git", lambda *a: "sha")

    def freeze(files):
        monkeypatch.setattr(evaluator, "freeze_state", lambda: (dict(files), dict(files)))
    return freeze


def _refused(args, out):
    with pytest.raises(SystemExit) as e:
        run_h28.guard(args, out)
    return e.value.code


def test_unfrozen_catalogue_refused(env, tmp_path, capsys):
    env({"protocol/other.json": "0" * 64})
    assert _refused(_args("exp-h28-001"), tmp_path) == 2
    assert "adapters.py" in capsys.readouterr().err
    assert not (tmp_path / "cases.jsonl").exists() and not (tmp_path / "run-pre.json").exists()


def test_frozen_but_stale_catalogue_refused(env, tmp_path, capsys):
    env({REL: "f" * 64})
    assert _refused(_args("exp-h28-001"), tmp_path) == 2
    assert "adapters.py" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_frozen_matching_catalogue_passes(env, tmp_path):
    env({REL: CUR})
    assert run_h28.guard(_args("exp-h28-001"), tmp_path) == {}


def test_dev_id_not_refused_by_the_catalogue_check(env, tmp_path):
    env({"protocol/other.json": "0" * 64})
    assert run_h28.guard(_args("exp-h28-x-dev-1"), tmp_path) == {}
