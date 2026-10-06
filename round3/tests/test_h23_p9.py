"""P9: minimum overrides are recorded and dev-only; comparative LOC/components populated; concurrency mutation proof."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

from r3_harness.h23 import comparative, evaluator, mutation
from r3_harness.h23.corpus import load_specs
from tests.fakes.h23_fakes import load

ROUND3 = Path(__file__).resolve().parents[1]
TH = json.loads((ROUND3 / "protocol" / "thresholds.json").read_text())


def _run(tmp_path, exp):
    cmd = [sys.executable, str(ROUND3 / "scripts" / "run_h23.py"), "--test-variants", "--sequences", "20",
           "--mutation-sequences", "5", "--out-root", str(tmp_path), "--exp-id", exp, "--variants", "fake-correct"]
    subprocess.run(cmd, check=True, capture_output=True)


def _eval(tmp_path, exp, *extra):
    return subprocess.run([sys.executable, str(ROUND3 / "scripts" / "evaluate_h23.py"), exp, "--out-root",
                           str(tmp_path), *extra], capture_output=True, text=True)


def test_override_is_recorded_in_verdict_json_and_in_every_variant_reasons(tmp_path):
    _run(tmp_path, "exp-h23-dev9")
    r = _eval(tmp_path, "exp-h23-dev9", "--min-sequences", "10", "--min-concurrency", "5")
    assert r.returncode == 0, r.stderr
    v = json.loads((tmp_path / "exp-h23-dev9" / "verdict.json").read_text())
    assert v["minimum_overrides"] == {"min_sequences": 10, "min_concurrency": 5}
    for var in v["variants"].values():
        assert var["minimum_overrides"] == v["minimum_overrides"]
        assert "DEV ONLY: minimum min_sequences overridden to 10" in var["reasons"]
        assert "DEV ONLY: minimum min_concurrency overridden to 5" in var["reasons"]


def test_no_override_means_empty_record_and_no_dev_reason(tmp_path):
    _run(tmp_path, "exp-h23-dev8")
    assert _eval(tmp_path, "exp-h23-dev8").returncode == 0
    v = json.loads((tmp_path / "exp-h23-dev8" / "verdict.json").read_text())
    assert v["minimum_overrides"] == {}
    assert not [x for var in v["variants"].values() for x in var["reasons"] if x.startswith("DEV ONLY")]


def test_override_on_a_non_dev_experiment_id_exits_2_known_negative(tmp_path):
    _run(tmp_path, "exp-h23-001")
    for flag in ("--min-sequences", "--min-concurrency"):
        r = _eval(tmp_path, "exp-h23-001", flag, "10")
        assert r.returncode == 2 and "dev experiment" in r.stderr
    assert not (tmp_path / "exp-h23-001" / "verdict.json").exists()
    assert _eval(tmp_path, "exp-h23-001").returncode == 0  # same id without override is allowed


def _verify_tree(tmp_path, exp, overrides):
    root = tmp_path / "r3"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(ROUND3 / "scripts" / "verify_h23.sh", root / "scripts")
    d = root / "experiments" / "h23" / exp
    d.mkdir(parents=True)
    (d / "verdict.json").write_text(json.dumps({"minimum_overrides": overrides}))
    return subprocess.run(["bash", str(root / "scripts" / "verify_h23.sh"), exp], capture_output=True, text=True,
                          env={"PY": sys.executable, "PATH": "/usr/bin:/bin"})


def test_verify_fails_on_overrides_in_a_non_dev_verdict(tmp_path):
    r = _verify_tree(tmp_path, "exp-h23-001", {"min_sequences": 1000})
    assert r.returncode == 1 and "FROZEN MINIMUM OVERRIDDEN" in r.stdout
    r = _verify_tree(tmp_path / "b", "exp-h23-001", {})  # empty record passes this check (fails later: no evaluator copy)
    assert "FROZEN MINIMUM OVERRIDDEN" not in r.stdout
    r = _verify_tree(tmp_path / "c", "exp-h23-dev1", {"min_sequences": 1000})
    assert "FROZEN MINIMUM OVERRIDDEN" not in r.stdout


def test_minimum_overrides_ignores_values_equal_to_the_frozen_ones():
    frozen = TH["H23"]["min_adversarial_sequences"]
    assert evaluator.minimum_overrides(TH, frozen, evaluator.MIN_CONCURRENCY) == {}
    assert evaluator.minimum_overrides(TH, frozen - 1, None) == {"min_sequences": frozen - 1}


def test_comparative_loc_and_components_on_the_real_tree():
    for v in ("paladin", "conventional"):
        loc = comparative.security_specific_loc(v)
        comps = comparative.security_specific_components(v)
        assert loc["total"] > 0 and 0 < loc["excluding_vendored_unchanged"] <= loc["total"]
        assert comps and all((ROUND3 / c).is_file() for c in comps) and comps == sorted(set(comps))
    assert comparative.security_specific_loc("conventional")["total"] == \
        comparative.security_specific_loc("conventional")["excluding_vendored_unchanged"]
    p = comparative.security_specific_loc("paladin")
    assert p["excluding_vendored_unchanged"] < p["total"]  # vendored unchanged files are really excluded


def test_comparative_record_is_populated_never_null(tmp_path):
    _run(tmp_path, "exp-h23-dev7")
    src = tmp_path / "exp-h23-dev7" / "fake-correct"
    for name in ("paladin", "conventional"):  # evidence of a fake relabelled so the tree-derived fields resolve
        shutil.copytree(src, tmp_path / "exp-h23-dev7" / name)
    shutil.rmtree(src)
    res = evaluator.evaluate_experiment(tmp_path / "exp-h23-dev7", TH, 10, 5)
    comp = res["comparative"]
    for n in ("paladin", "conventional"):
        loc = comp["security_specific_loc"][n]
        assert loc["total"] > 0 and loc["excluding_vendored_unchanged"] > 0
        assert comp["security_specific_components"][n]
    assert comparative.security_specific_loc("nonexistent") is None


def test_concurrency_mutant_proof_records_kills_over_many_scenarios():
    assert mutation.CONC_N >= 300
    got = mutation.prove(lambda m: load("fake-correct", m), load_specs(), 5)
    e = got["unsynchronized_commit"]
    assert e["killed"] and e["scenarios"] == mutation.CONC_N and e["kills"] == e["gain"]["concurrency_unserializable"] > 0
    assert got["backstop_bypass"]["scenarios"] == 5 and "kills" in got["backstop_bypass"]
