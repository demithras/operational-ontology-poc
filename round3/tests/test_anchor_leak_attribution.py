"""Proves the conftest anchor-leak check in both directions using nested pytest sessions:
(1) a test that leaks an anchor is caught (exit 1 + ANCHOR LEAK line, process killed);
(2) an anchor started by an unrelated process during the session is NOT counted (and an orphan of it is left alone)."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
LEAKY = '''
import os, tempfile
from r3_shared.anchor import start_anchor
def test_leaks():
    d = tempfile.mkdtemp()
    start_anchor(os.path.join(d, "anchor"), os.path.join(d, "s"))   # never closed
'''
CLEAN = "def test_noop():\n    assert True\n"


def _session(tmp: Path, body: str, name: str):
    shutil.copy(HERE / "conftest.py", tmp / "conftest.py")
    (tmp / name).write_text(body)
    env = {**os.environ, "PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp / name)],
                          capture_output=True, text=True, env=env, cwd=str(tmp))


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def test_deliberate_leak_is_caught(tmp_path):
    r = _session(tmp_path, LEAKY, "test_leaky.py")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ANCHOR LEAK: 1 " in r.stdout, r.stdout
    pid = int(r.stdout.split("still alive: [")[1].split("]")[0])
    assert not _alive(pid)


def test_foreign_anchor_not_counted(tmp_path):
    foreign = tempfile.mkdtemp(prefix="foreign")
    p = subprocess.Popen([sys.executable, "-m", "r3_shared.anchor_server", "--dir", f"{foreign}/anchor", "--sock", f"{foreign}/s"],
                         env={**os.environ, "PYTHONPATH": str(SRC)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True)
    try:
        assert p.stdout.readline().startswith(b"READY")
        r = _session(tmp_path, CLEAN, "test_clean.py")   # runs while the foreign anchor is alive
        assert r.returncode == 0 and "ANCHOR LEAK" not in r.stdout, r.stdout + r.stderr
        assert p.poll() is None, "foreign anchor must not be killed"
    finally:
        p.kill()
        p.wait()
        shutil.rmtree(foreign, ignore_errors=True)
