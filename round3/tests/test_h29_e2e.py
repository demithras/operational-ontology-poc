"""End-to-end chain over REAL services and spawned hosts (G3-E31b lesson): scripts/run_h29.sh -> evaluate -> verify on FakeHonestG5 and
FakeFailOpenAuth; launcher refusals as subprocess exits; changed frozen file -> INVALID; serial vs 2-worker parallel byte identity."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from r3_harness.h29 import evalchecks as EC, evaluator, runner
from r3_harness.h29.svcset import SvcSet

R3 = EC.ROUND3
PY = sys.executable
ID = "exp-h29-e2e-dev-1"
HONEST, BAD = "tests.fakes.fake_h29:FakeHonestG5", "tests.fakes.fake_h29:FakeFailOpenAuth"
ENV = {**os.environ, "PYTHONPATH": str(R3 / "src"), "PY": PY}


@pytest.fixture(scope="module")
def exp():
    out = Path(tempfile.mkdtemp(prefix="h29e", dir="/tmp"))
    r = subprocess.run(["bash", str(R3 / "scripts/run_h29.sh"), "--exp-id", ID, "--variants", f"{HONEST},{BAD}", "--workers", "2", "--out-root", str(out),
                        "--seed", "2911", "--sequences", "112", "--controls", "8", "--boundary", "16", "--test-variants", "--mutants", "--mutation-env", "112"],
                       capture_output=True, text=True, env=ENV, timeout=1500)
    assert r.returncode == 0, r.stderr[-2000:] + r.stdout[-1000:]
    leaks = subprocess.run("ps -eo pid,command | grep -E 'r3_shared\\.(anchor_server|extworld_server|authsvc_server|host)' | grep /tmp/r3h29 | grep -v grep",
                           shell=True, capture_output=True, text=True).stdout
    assert leaks == ""                                                                            # the launcher left no server of its own behind
    return out


def evaluate(out: Path) -> dict:
    r = subprocess.run([PY, str(R3 / "scripts/evaluate_h29.py"), str(out / ID), "--print-only"], capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_chain_verdicts_and_verify(exp):
    v = evaluate(exp)["variants"]
    assert v["FakeHonestG5"]["verdict"] == "SUPPORTED", v["FakeHonestG5"]["reasons"]
    assert v["FakeFailOpenAuth"]["verdict"] == "REJECTED"
    assert any(r.startswith("DEV ONLY") for r in v["FakeHonestG5"]["reasons"])                    # stamped dev overrides
    (exp / ID / "verdict.json").write_text(json.dumps(evaluate(exp), indent=1, sort_keys=True, default=str) + "\n")
    r = subprocess.run(["bash", str(R3 / "scripts/verify_h29.sh"), str(exp / ID)], capture_output=True, text=True, env=ENV)
    assert r.returncode == 0 and "verdict reproduces" in r.stdout, r.stdout + r.stderr


def test_services_were_started_and_closed_by_the_launcher(exp):
    man = json.loads((exp / ID / "FakeHonestG5" / "manifest.json").read_text())["raw_observations"]
    for k in ("anchor", "ext", "auth"):
        assert len(man["closes"][k]) == 2 and all("error" not in c for c in man["closes"][k])
    assert (exp / ID / "FakeHonestG5" / "svc" / "ext-1" / "external.db").is_file()


def test_changed_frozen_file_makes_the_run_invalid(exp, tmp_path, monkeypatch):
    fz = tmp_path / "FREEZE_G5.json"
    fz.write_text(json.dumps({"files": {"src/r3_harness/h29/faults.py": "0" * 64}}))
    monkeypatch.setattr(EC, "FREEZE_G5", fz)
    thr = json.loads((R3 / "protocol/thresholds.json").read_text())
    res = evaluator.evaluate_variant(exp / ID / "FakeHonestG5", thr, "FakeHonestG5", True)
    assert res["verdict"] == "INVALID" and any("faults.py" in r for r in res["reasons"])


def test_non_dev_id_refuses_without_services_and_writes_nothing(tmp_path):
    # services-up case: the refusal must NOT depend on freeze/manifest state (a complete freeze once let it launch a full official run),
    # so it uses a candidate tag != HEAD, which guard() refuses right after the service check.
    for stopped in ("anchor", "ext", "auth", None):
        sv = SvcSet(1)
        try:
            if stopped:
                a, x, u = sv.procs[0]
                {"anchor": a, "ext": x, "auth": u}[stopped].proc.kill()
            env = {**ENV, "R3_H29_SVC": str(sv.root), "R3_H29_WORKERS": "1"}
            r = subprocess.run([PY, str(R3 / "scripts/run_h29.py"), "run", "--exp-id", "exp-h29-001", "--variant", "paladin", "--candidate-tag", "HEAD~1",
                                "--out-root", str(tmp_path)], capture_output=True, text=True, env=env, timeout=120)
            assert r.returncode == 2, r.stderr[-500:]
            branch = "service_presence" if stopped else "candidate_tag"
            assert f"refusing [{branch}]" in r.stderr, r.stderr[-500:]
            assert not (tmp_path / "exp-h29-001").exists()
        finally:
            sv.cleanup()


def test_serial_and_parallel_runs_give_byte_identical_evidence():
    outs = []
    for w in (1, 2):
        sv = SvcSet(w)
        try:
            out = Path(tempfile.mkdtemp(prefix="h29i", dir="/tmp"))
            runner.run_variant(str(sv.root), HONEST, "FakeHonestG5", out, "exp-h29-ident-dev-1", 2911, 16, 2, 4, w, extra_paths=[str(R3)])
            outs.append((out / "cases.jsonl").read_bytes())
        finally:
            sv.cleanup()
    assert outs[0] == outs[1] and len(outs[0]) > 1000
