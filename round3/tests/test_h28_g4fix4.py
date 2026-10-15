"""G4-E26 / fix4: twins on the identical absolute clock (byte-exact R28-11a, nothing excluded), known negatives still caught, the parallel
mutation proof equals the sequential one, evaluate/verify accept an id or a path."""
import copy
import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from r3_harness.h28.factories import NamedFactory
from r3_harness.h28 import judge, mutation
from tests.fakes import fake_h28
from tests.h28_util import run_corpus

R3 = Path(__file__).resolve().parents[1]
_c = {}


def corpus(name):
    if name not in _c:
        _c[name] = run_corpus(lambda m, n=name: fake_h28.load(n, m), cases=60, controls=6)
    return _c[name]


def test_twins_run_on_the_identical_absolute_schedule():
    J = corpus("FakeHonest")[0]
    pairs = [(k["byz"], k["twin"]) for k in J["recs"].values() if "twin" in k]
    assert len(pairs) >= 40
    for B, T in pairs:
        assert B["start_tick"] == T["start_tick"] and B["end_tick"] == T["end_tick"], (B["case"], B["start_tick"], T["start_tick"])
        assert [(q["i"], q["replay"], q["tick"]) for q in B["requests"]] == [(q["i"], q["replay"], q["tick"]) for q in T["requests"]]
        assert judge.twin_diff(B, T) == []


def test_twin_lives_in_its_own_world():
    J = corpus("FakeHonest")[0]
    deps = {k["twin"]["dep"] for k in J["recs"].values() if "twin" in k}
    main, twin = [], []
    for r in J["ledger"]["effects"]:
        (twin if r["deployment"] in deps else main).append(r)
    assert twin and main


def test_decision_changing_adapter_is_caught_by_the_twin_differential():
    _, agg, _, _ = corpus("FakeAdapterDecision")
    assert agg["governance_sub"].get("adapter_influenced_decision", 0) > 0
    assert {c for c, v in agg["classes"].items() if v["count"]} == {"governance_in_adapter"}


@pytest.mark.parametrize("field,value", [("tick", 114), ("effect_digest", "forged")])
def test_envelope_only_difference_is_caught(field, value):
    """Known negative: take a real clean twin pair and change ONLY one envelope field of the Byzantine side."""
    J = corpus("FakeHonest")[0]
    for k in J["recs"].values():
        B, T = k["byz"], k.get("twin")
        if T is None or not any(e.get("envelope_text") for log in B["recorder"].values() for e in log):
            continue
        B2 = copy.deepcopy(B)
        for log in B2["recorder"].values():
            for e in log:
                if e.get("envelope_text"):
                    d = json.loads(e["envelope_text"])
                    d["decision"][field] = value
                    e["envelope_text"] = json.dumps(d)
        assert judge.twin_diff(B, T) == []
        assert judge.twin_diff(B2, T) == ["envelope"]
        return
    pytest.fail("no pair with an envelope")


def test_parallel_mutation_proof_equals_sequential():
    mk = NamedFactory("fake-FakeHonest")
    a = mutation.prove(mk, "fake", 2811, tempfile.mkdtemp(prefix="h28pa"), per_prim=2, extra=6, workers=1)
    b = mutation.prove(mk, "fake", 2811, tempfile.mkdtemp(prefix="h28pb"), per_prim=2, extra=6, workers=4)
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


@pytest.mark.parametrize("script", ["evaluate_h28.py", "verify_h28.sh"])
def test_scripts_document_and_accept_id_or_path(script):
    cmd = [str(R3 / "scripts" / script), "--help"] if script.endswith(".sh") else [str(R3 / ".venv" / "bin" / "python"), str(R3 / "scripts" / script), "--help"]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    assert "path" in out and "id" in out
    bad = [str(R3 / "scripts" / script), "/nonexistent/exp-h28-x"] if script.endswith(".sh") else [str(R3 / ".venv" / "bin" / "python"), str(R3 / "scripts" / script), "/nonexistent/exp-h28-x"]
    r = subprocess.run(bad, capture_output=True, text=True)
    assert r.returncode == 2 and "no such experiment" in r.stderr
