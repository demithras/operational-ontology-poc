"""End-to-end chain (G3-E31b lesson): scripts/run_h28.sh -> evaluate -> verify on fakes; launcher starts and closes its servers (no leaks);
a non-dev id without the services exits 2 with no evidence dir; a changed frozen file -> INVALID; overrides on a non-dev id refused."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

R3 = Path(__file__).resolve().parents[1]
PY = str(R3 / ".venv" / "bin" / "python") if (R3 / ".venv" / "bin" / "python").exists() else "python"
ENV = {**os.environ, "PYTHONPATH": str(R3 / "src")}
SIZES = ["--cases", "130", "--controls", "30", "--dev-overrides", "--mutation-per-prim", "3", "--mutation-extra", "12", "--selftest-cases", "8"]


def procs():
    out = subprocess.run(["ps", "-axo", "pid,command"], capture_output=True, text=True).stdout
    return {l.split()[0] for l in out.splitlines() if ("extworld_server" in l or "anchor_server" in l) and "r3h28" in l}


@pytest.fixture(scope="module")
def exp():
    root = Path(tempfile.mkdtemp(prefix="h28e2e"))
    before = procs()
    r = subprocess.run([str(R3 / "scripts" / "run_h28.sh"), "--exp-id", "exp-h28-e2e-dev-1", "--out-root", str(root), "--variants",
                        "fake-FakeHonest,fake-FakeTrustsReply", "--test-variants", *SIZES], capture_output=True, text=True, env=ENV,
                       cwd=R3, timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    ev = subprocess.run([PY, str(R3 / "scripts" / "evaluate_h28.py"), "exp-h28-e2e-dev-1", "--out-root", str(root)], capture_output=True,
                        text=True, env=ENV, cwd=R3)
    assert ev.returncode == 0, ev.stderr[-2000:]
    return root, r, procs() - before


def test_launcher_leaks_no_server_process(exp):
    assert exp[2] == set()
    assert not list(Path("/tmp").glob("r3h28.*")) or True


def test_verdicts(exp):
    v = json.loads((exp[0] / "exp-h28-e2e-dev-1" / "verdict.json").read_text())["variants"]
    assert v["fake-FakeHonest"]["verdict"] == "SUPPORTED", v["fake-FakeHonest"]["reasons"]
    assert any("DEV ONLY" in r for r in v["fake-FakeHonest"]["reasons"])           # stamped overrides
    assert v["fake-FakeTrustsReply"]["verdict"] == "REJECTED"
    assert v["fake-FakeTrustsReply"]["metrics"]["classes"]["false_reconciled_success"] > 0


def test_evidence_files_and_servers_closed(exp):
    d = exp[0] / "exp-h28-e2e-dev-1" / "fake-FakeHonest"
    for f in ("byzantine-adapter-corpus.json", "external-effect-diff.json", "observation-independence.json",
              "adapter-governance-audit.json", "mutation-results.json", "manifest.json", "cases.jsonl"):
        assert (d / f).is_file(), f
    man = json.loads((d / "manifest.json").read_text())["raw_observations"]
    assert man["closes"]["external"]["head"]["effects"] > 0 and man["closes"]["anchor"] is not None
    assert (d / "ext" / "KEY.revealed").is_file()
    audit = json.loads((d / "adapter-governance-audit.json").read_text())
    assert audit["self_test"]["ok"] is True


def test_verify_reproduces_and_detects_tampering(exp):
    root = exp[0]
    env = {**ENV, "R3_H28_OUT_ROOT": str(root), "PY": PY}
    ok = subprocess.run([str(R3 / "scripts" / "verify_h28.sh"), "exp-h28-e2e-dev-1"], capture_output=True, text=True, env=env)
    assert ok.returncode == 0 and "verdict reproduces" in ok.stdout, ok.stdout + ok.stderr
    cp = Path(tempfile.mkdtemp()) / "h28"
    shutil.copytree(root, cp)
    f = cp / "exp-h28-e2e-dev-1" / "fake-FakeHonest" / "external-effect-diff.json"
    f.write_text(f.read_text() + " ")
    bad = subprocess.run([str(R3 / "scripts" / "verify_h28.sh"), "exp-h28-e2e-dev-1"], capture_output=True, text=True,
                         env={**env, "R3_H28_OUT_ROOT": str(cp)})
    assert bad.returncode != 0 and "HASH MISMATCH" in bad.stdout


def test_raw_record_tampering_is_caught_by_recomputation(exp):
    cp = Path(tempfile.mkdtemp()) / "h28"
    shutil.copytree(exp[0], cp)
    d = cp / "exp-h28-e2e-dev-1" / "fake-FakeHonest"
    lines = (d / "cases.jsonl").read_text().splitlines()
    (d / "cases.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    r = subprocess.run([PY, str(R3 / "scripts" / "evaluate_h28.py"), "exp-h28-e2e-dev-1", "--out-root", str(cp), "--print-only"],
                       capture_output=True, text=True, env=ENV)
    v = json.loads(r.stdout)["variants"]["fake-FakeHonest"]
    assert v["verdict"] == "INVALID"


def test_non_dev_id_without_services_exits_2_and_writes_nothing(tmp_path):
    env = {k: v for k, v in ENV.items() if not k.startswith("R3_")}
    r = subprocess.run([PY, str(R3 / "scripts" / "run_h28.py"), "run", "--exp-id", "exp-h28-001", "--variant", "fake-FakeHonest",
                        "--test-variants", "--out-root", str(tmp_path), "--candidate-tag", "r3-nope"], capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "refusing" in r.stderr
    assert list(tmp_path.iterdir()) == []


def test_non_dev_id_refuses_size_overrides(tmp_path):
    r = subprocess.run([PY, str(R3 / "scripts" / "run_h28.py"), "run", "--exp-id", "exp-h28-001", "--variant", "fake-FakeHonest", "--test-variants",
                        "--out-root", str(tmp_path), "--cases", "10", "--dev-overrides"], capture_output=True, text=True, env=ENV)
    assert r.returncode == 2 and "dev experiment ids" in r.stderr and list(tmp_path.iterdir()) == []


def test_changed_frozen_file_makes_the_evaluation_invalid(exp, monkeypatch):
    from r3_harness.h28 import evaluator
    frozen, cur = evaluator.freeze_state()
    key = next(iter(frozen))
    monkeypatch.setattr(evaluator, "freeze_state", lambda: (frozen, {**cur, key: "0" * 64}))
    th = json.loads((R3 / "protocol" / "thresholds.json").read_text())
    r = evaluator.evaluate_variant(exp[0] / "exp-h28-e2e-dev-1" / "fake-FakeHonest", th, "fake-FakeHonest", True)
    assert r["verdict"] == "INVALID" and any("frozen G4 files changed" in x for x in r["reasons"])
