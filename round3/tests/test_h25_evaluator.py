"""H25 evaluator: verdict mapping on real pipeline runs of the fakes (dev sizes), tamper and missing-key behaviour."""
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from r3_harness.h25 import analyze as AN
from r3_harness.h25 import evaluator as EV
from r3_harness.h25.runner import write_evidence
from tests.h25_util import small_pipeline

TH = json.loads((Path(__file__).resolve().parents[1] / "protocol" / "thresholds.json").read_text())
DEV = 150


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("h25runs")
    return {n: small_pipeline(n, root, exp=f"exp-h25-dev-{n}", cases=140, races=14)
            for n in ("fake-honest", "fake-alwaysoracleneeded", "fake-quorumweak", "fake-domainbranch", "fake-meritreader")}


def ev(runs, name, **kw):
    return EV.evaluate_variant(runs[name] / name, TH, name, min_cases=DEV, **kw)


def test_honest_is_supported(runs):
    r = ev(runs, "fake-honest")
    assert r["verdict"] == "SUPPORTED", r["reasons"]
    assert r["metrics"]["mutation_kill_rate"] == 1.0 and r["metrics"]["procedural_equality"] == 1.0
    assert r["minimum_overrides"] == {"min_cases": DEV}
    assert any("DEV ONLY" in x for x in r["reasons"])


def test_honest_fails_the_frozen_minimum_without_override(runs):
    r = EV.evaluate_variant(runs["fake-honest"] / "fake-honest", TH, "fake-honest")
    assert r["verdict"] == "INCONCLUSIVE" and any("< 10000" in x for x in r["reasons"])


def test_always_oracle_needed_is_inconclusive_never_supported(runs):
    r = ev(runs, "fake-alwaysoracleneeded")
    assert r["verdict"] == "INCONCLUSIVE", r["reasons"]
    assert any("progress" in x for x in r["reasons"])


@pytest.mark.parametrize("name", ["fake-quorumweak", "fake-domainbranch", "fake-meritreader"])
def test_known_negatives_are_rejected(runs, name):
    r = ev(runs, name)
    assert r["verdict"] == "REJECTED", (name, r["reasons"])


def test_domain_branch_reason_cites_the_audit(runs):
    r = ev(runs, "fake-domainbranch")
    assert r["metrics"]["domain_branches"] > 0


def test_dual_verdict_shape(runs):
    root = runs["fake-honest"]
    out = EV.evaluate_experiment(root, TH, DEV)
    assert set(out) >= {"paladin_verdict", "conventional_verdict", "comparative", "evaluator_sha256", "variants"}
    assert out["paladin_verdict"] == "INCONCLUSIVE"  # no variant named paladin in this experiment: never SUPPORTED


def _copy(runs, tmp_path, name="fake-honest"):
    dst = tmp_path / name
    shutil.copytree(runs[name] / name, dst)
    return dst


def test_missing_file_is_invalid(runs, tmp_path):
    d = _copy(runs, tmp_path)
    (d / "oracle-boundary-audit.json").unlink()
    assert EV.evaluate_variant(d, TH, "x", min_cases=DEV)["verdict"] == "INVALID"


def test_hash_tamper_is_invalid(runs, tmp_path):
    d = _copy(runs, tmp_path)
    p = d / "safe-progress.json"
    p.write_text(p.read_text().replace("1.0", "0.5", 1) if "1.0" in p.read_text() else p.read_text() + " ")
    r = EV.evaluate_variant(d, TH, "x", min_cases=DEV)
    assert r["verdict"] == "INVALID" and any("sha256" in x for x in r["reasons"])


def test_frozen_g3_drift_is_invalid(runs, monkeypatch):
    real = EV.freeze_g3
    monkeypatch.setattr(EV, "freeze_g3", lambda: {**real(), "spec/protections/PROT-H25.md": "0" * 64})
    assert EV.evaluate_variant(runs["fake-honest"] / "fake-honest", TH, "x", min_cases=DEV)["verdict"] == "INVALID"


def _rewrite(runs, tmp_path, mres=None, dba=None, oba=None):
    src = runs["fake-honest"] / "fake-honest"
    d = tmp_path / "rw"
    d.mkdir()
    shutil.copy(src / AN.CASES_FILE, d / AN.CASES_FILE)
    load = lambda f: json.loads((src / f).read_text())  # noqa: E731
    write_evidence(d, "x", "exp-h25-dev", 1, 1, 1, 0, mres if mres is not None else load(AN.FILES[4]),
                   dba if dba is not None else load(AN.FILES[2]), oba if oba is not None else load(AN.FILES[3]))
    return d


@pytest.mark.parametrize("which,val", [("mres", {}), ("dba", {"domain_branch": None}), ("oba", {}),
                                       ("oba", {"judgment_flip": None, "merit_invariance": {"fabricated": None}})])
def test_missing_or_none_keys_never_supported(runs, tmp_path, which, val):
    d = _rewrite(runs, tmp_path, **{which: val})
    r = EV.evaluate_variant(d, TH, "x", min_cases=DEV)
    assert r["verdict"] in ("INCONCLUSIVE", "INVALID"), r["reasons"]


def test_unique_case_counting(tmp_path):
    rows = []
    for i in range(5):
        rows.append({"id": f"case-1-{i}", "model": "collegial", "domain": "project", "digest": "same" if i < 3 else f"d{i}",
                     "calls": [], "case_classes": [], "classes": [], "tags": [], "final": {}, "redraws": 0})
    with gzip.open(tmp_path / AN.CASES_FILE, "wt") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    a = AN.analyze(tmp_path)
    assert a["cases"] == 5 and a["unique_cases"] == 3


def test_minimum_override_refused_for_official_ids(tmp_path):
    root = Path(__file__).resolve().parents[1]
    p = subprocess.run([sys.executable, str(root / "scripts" / "evaluate_h25.py"), "exp-h25-001", "--min-cases", "10",
                        "--out-root", str(tmp_path)], capture_output=True, text=True)
    assert p.returncode == 2 and "dev experiment ids" in p.stderr


def test_oracle_independence_scan_passes_and_catches_a_variant_import(tmp_path, monkeypatch):
    ok, bad = EV.oracle_independent()
    assert ok, bad
    fake_root = tmp_path / "src" / "r3_oracle"
    fake_root.mkdir(parents=True)
    (fake_root / "x.py").write_text("from paladin import variant\n")
    monkeypatch.setattr(EV, "ROUND3", tmp_path)
    ok, bad = EV.oracle_independent()
    assert not ok and "paladin" in bad[0]
