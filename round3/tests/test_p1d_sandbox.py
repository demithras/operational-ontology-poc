"""E3/E4: harness-side writes to the anchor dir fail under scripts/run_sandboxed.sh (known-negative); writes elsewhere work
(known-positive). If sandbox-exec is unavailable this test FAILS (never skips): the enforcement level would be invalid."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from r3_shared.anchor import AnchorClient, verify_anchor_log

ROUND3 = Path(__file__).resolve().parents[1]
PROBE = r'''
import json, os, sys
d, ok = os.environ["R3_ANCHOR_DIR"], sys.argv[1]
out = {}
def attempt(name, fn):
    try:
        fn(); out[name] = "ok"
    except PermissionError: out[name] = "PermissionError"
    except Exception as e: out[name] = type(e).__name__
attempt("append_log", lambda: open(os.path.join(d, "anchor.log"), "ab").write(b"x\n"))
attempt("truncate_log", lambda: open(os.path.join(d, "anchor.log"), "wb"))
attempt("create_file", lambda: open(os.path.join(d, "evil"), "w").write("x"))
attempt("chmod_dir", lambda: os.chmod(d, 0o777))
attempt("chmod_log", lambda: os.chmod(os.path.join(d, "anchor.log"), 0o666))
attempt("unlink_log", lambda: os.unlink(os.path.join(d, "anchor.log")))
attempt("mkdir", lambda: os.mkdir(os.path.join(d, "sub")))
attempt("write_other_dir", lambda: open(os.path.join(ok, "fine"), "w").write("x"))
from r3_shared.anchor import AnchorClient
c = AnchorClient(os.environ["R3_ANCHOR_SOCK"])
r = c.append("probe", 1, "d1", "a"*64); c.append("probe", 2, "d2", "b"*64)
out["socket_append"] = r["seq"]
print(json.dumps(out))
'''


def test_sandbox_exec_available_not_skipped():
    assert shutil.which("sandbox-exec"), "sandbox-exec unavailable: Q1 option (a) cannot be enforced - report to the author"


def test_anchor_dir_write_denied_other_dir_allowed_and_log_verifies(tmp_path):
    anchor = tmp_path / "anchor"
    other = Path(tempfile.mkdtemp(prefix="r3other"))
    try:
        p = subprocess.run([str(ROUND3 / "scripts" / "run_sandboxed.sh"), str(anchor), sys.executable, "-c", PROBE, str(other)],
                           capture_output=True, text=True, timeout=120)
        assert p.returncode == 0, p.stderr
        out = json.loads(p.stdout.strip().splitlines()[-1])
        for k in ("append_log", "truncate_log", "create_file", "chmod_dir", "chmod_log", "unlink_log", "mkdir"):
            assert out[k] == "PermissionError", (k, out)           # known negatives
        assert out["write_other_dir"] == "ok" and (other / "fine").exists()  # known positive
        assert out["socket_append"] == 1                              # the only write path is the anchor service
        assert not (anchor / "evil").exists() and not (anchor / "sub").exists()
        head = json.loads(p.stderr.split("ANCHOR_CLOSED ")[1].splitlines()[0])
        v = verify_anchor_log(anchor, expected_head=head)             # untouched log verifies after close
        assert v["ok"] and v["entries"] == 2, v
    finally:
        shutil.rmtree(other, ignore_errors=True)


def test_control_without_sandbox_the_same_probe_succeeds(tmp_path):
    """Non-vacuity: outside the runner the same writes DO succeed, so the denials above come from the sandbox."""
    d = tmp_path / "plain"
    d.mkdir()
    code = "import os,sys; open(os.path.join(sys.argv[1],'evil'),'w').write('x'); os.chmod(sys.argv[1],0o755)"
    assert subprocess.run([sys.executable, "-c", code, str(d)]).returncode == 0 and (d / "evil").exists()


def test_runner_refuses_bad_usage_and_propagates_exit_code(tmp_path):
    sh = str(ROUND3 / "scripts" / "run_sandboxed.sh")
    assert subprocess.run([sh, str(tmp_path / "a")], capture_output=True).returncode == 64
    p = subprocess.run([sh, str(tmp_path / "b"), sys.executable, "-c", "raise SystemExit(7)"], capture_output=True, text=True, timeout=120)
    assert p.returncode == 7 and "ANCHOR_CLOSED" in p.stderr
