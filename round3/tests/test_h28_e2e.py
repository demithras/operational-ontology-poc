"""End-to-end chain (G3-E31b lesson): scripts/run_h28.sh -> evaluate -> verify on fakes; launcher starts and closes its servers (no leaks);
a non-dev id without the services exits 2 with no evidence dir; a changed frozen file -> INVALID; overrides on a non-dev id refused."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

R3 = Path(__file__).resolve().parents[1]
PY = str(R3 / ".venv" / "bin" / "python") if (R3 / ".venv" / "bin" / "python").exists() else "python"
ENV = {**os.environ, "PYTHONPATH": str(R3 / "src")}
SIZES = ["--cases", "130", "--controls", "30", "--dev-overrides", "--mutation-per-prim", "3", "--mutation-extra", "12", "--selftest-cases", "8"]


MARKS = ("r3_shared.anchor_server", "r3_shared.extworld_server")


def servers_in(root):
    """pid -> cmdline of live anchor/extworld servers whose command line names a path inside `root` (exact attribution, as in
    tests/conftest.py; never a machine-wide diff or ppid)."""
    roots = {os.path.realpath(str(root)), str(root)}
    roots |= {r.replace("/private", "", 1) for r in roots}
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    res = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and parts[0].isdigit() and any(m in parts[1] for m in MARKS) and any(f"{r.rstrip('/')}/" in parts[1] for r in roots):
            res[int(parts[0])] = parts[1]
    return res


def fake_server(mark, d):
    """A stand-in process whose command line looks like a launcher server started with --dir d."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", mark, "--dir", str(d)])


@pytest.fixture(scope="module")
def shim(tmp_path_factory):
    """PATH shim: run_h28.sh makes its work dir with an absolute `mktemp -d /tmp/r3h28.XXXXXX`; redirect that template into this test's
    private root so every server the launcher starts carries the root in its command line."""
    real = shutil.which("mktemp")
    root = Path(os.path.realpath(tempfile.mkdtemp(prefix="h28w")))  # short path (AF_UNIX limit), under the session TMPDIR
    bindir = Path(tempfile.mkdtemp(prefix="h28b"))
    (bindir / "mktemp").write_text(f'#!/bin/bash\nargs=()\nfor a in "$@"; do args+=("${{a/#\\/tmp\\/r3h28./{root}/r3h28.}}"); done\nexec {real} "${{args[@]}}"\n')
    (bindir / "mktemp").chmod(0o755)
    yield root, bindir
    shutil.rmtree(bindir, ignore_errors=True)
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture(scope="module")
def exp(shim):
    wroot, bindir = shim
    root = Path(tempfile.mkdtemp(prefix="h28e2e"))
    unrelated = fake_server(MARKS[1], Path(tempfile.mkdtemp(prefix="h28other")))  # alive during the run, NOT ours
    try:
        env = {**ENV, "PATH": f"{bindir}{os.pathsep}{ENV['PATH']}"}
        r = subprocess.run([str(R3 / "scripts" / "run_h28.sh"), "--exp-id", "exp-h28-e2e-dev-1", "--out-root", str(root), "--variants",
                            "fake-FakeHonest,fake-FakeTrustsReply", "--test-variants", *SIZES], capture_output=True, text=True, env=env,
                           cwd=R3, timeout=900)
        assert r.returncode == 0, r.stderr[-3000:]
        ev = subprocess.run([PY, str(R3 / "scripts" / "evaluate_h28.py"), "exp-h28-e2e-dev-1", "--out-root", str(root)], capture_output=True,
                            text=True, env=ENV, cwd=R3)
        assert ev.returncode == 0, ev.stderr[-2000:]
        yield root, r, servers_in(wroot), unrelated.pid, wroot
    finally:
        unrelated.kill()
        unrelated.wait()


def test_launcher_leaks_no_server_process(exp):
    root, _, leaked, unrelated_pid, wroot = exp
    assert leaked == {}, leaked
    # proof the attribution is live (not vacuous): the launcher's work dirs were under wroot (now removed), and the unrelated server is
    # alive yet was ignored
    assert subprocess.run(["ps", "-p", str(unrelated_pid)], capture_output=True).returncode == 0
    assert unrelated_pid not in leaked


def test_attribution_ignores_unrelated_and_catches_own_leftovers(shim):
    wroot, _ = shim
    other = fake_server(MARKS[1], Path(tempfile.mkdtemp(prefix="h28other")))
    mine = fake_server(MARKS[0], wroot / "r3h28.leftover" / "anchor")
    try:
        import time
        time.sleep(0.5)
        found = servers_in(wroot)
        assert mine.pid in found and other.pid not in found and len(found) == 1
    finally:
        for p in (other, mine):
            p.kill()
            p.wait()


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
