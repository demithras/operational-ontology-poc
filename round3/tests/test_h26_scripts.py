"""H26 scripts: dev-only overrides, honest 'not implemented yet - G3' for unbuilt variants, verify reproduces, fuzz seed sweep."""
import os
import subprocess
import sys
from pathlib import Path

from r3_harness.h26 import fuzz
from tests.fakes import fake_h26

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def sh(*a, **kw):
    return subprocess.run(list(a), capture_output=True, text=True, cwd=ROOT, env=ENV, **kw)


def test_run_refuses_reduced_counts_on_non_dev_ids(tmp_path):
    r = sh(PY, "scripts/run_h26.py", "--exp-id", "exp-h26-001", "--variants", "fake-honest", "--test-variants", "--pairs", "10",
           "--out-root", str(tmp_path))
    assert r.returncode == 2 and "dev ids" in r.stderr


def test_fake_variants_need_the_test_flag(tmp_path):
    r = sh(PY, "scripts/run_h26.py", "--exp-id", "exp-h26-dev", "--variants", "fake-honest", "--out-root", str(tmp_path))
    assert r.returncode == 2 and "--test-variants" in r.stderr


def test_unbuilt_real_variant_exits_2_with_the_honest_message(tmp_path):
    r = sh(PY, "scripts/run_h26.py", "--exp-id", "exp-h26-dev", "--variants", "paladin", "--pairs", "5", "--aa", "2", "--fuzz-calls", "10",
           "--out-root", str(tmp_path))
    if r.returncode == 0:  # a built variant: nothing to assert here, the conformance tests cover it
        return
    assert r.returncode == 2 and "not implemented yet - G3" in r.stderr


def test_evaluate_refuses_overrides_on_non_dev_ids(tmp_path):
    (tmp_path / "exp-h26-001").mkdir()
    r = sh(PY, "scripts/evaluate_h26.py", "exp-h26-001", "--out-root", str(tmp_path), "--min-pairs", "5")
    assert r.returncode == 2


def test_run_evaluate_verify_round_trip_reproduces(tmp_path):
    out = tmp_path / "root"
    r = sh(PY, "scripts/run_h26.py", "--exp-id", "exp-h26-dev", "--variants", "fake-honest", "--test-variants", "--pairs", "8", "--aa", "3",
           "--fuzz-calls", "40", "--mutation-pairs", "2", "--out-root", str(out))
    assert r.returncode == 0, r.stderr
    ov = ["--min-pairs", "8", "--min-aa", "3", "--min-fuzz-calls", "40", "--min-per-kind", "1", "--min-per-channel", "1", "--min-probes", "1"]
    e = sh(PY, "scripts/evaluate_h26.py", "exp-h26-dev", "--out-root", str(out), *ov)
    assert e.returncode == 0, e.stderr
    v = subprocess.run(["bash", "scripts/verify_h26.sh", "exp-h26-dev", *ov], capture_output=True, text=True, cwd=ROOT,
                       env={**ENV, "R3_H26_OUT_ROOT": str(out), "PY": PY})
    assert v.returncode == 0 and "verdict reproduces" in v.stdout, (v.stdout, v.stderr)


def test_fuzz_seed_sweep_never_raises():
    v = fake_h26.H26Variant()
    for seed in range(2000):
        out = fuzz.run(v, seed, 1)
        assert out["calls"] >= 0 and "existence_leak" in out
