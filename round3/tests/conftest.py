"""Session-level hygiene: fail the session if anchor_server processes IT started are still alive at the end.
Attribution is exact (never by ppid alone): at import time the session claims a private temp root and exports it as
TMPDIR (inherited by every child process, so by every start_anchor() caller). An anchor is ours iff its command line
names a --dir/--sock path inside that root (or inside pytest's own basetemp). Orphans of other sessions never match."""
import os
import shutil
import signal
import subprocess
import tempfile
import time

MARK = "r3_shared.anchor_server"
_ROOT = os.path.realpath(tempfile.mkdtemp(prefix="r3s", dir="/tmp"))  # short path: AF_UNIX limit
os.environ["TMPDIR"] = _ROOT
tempfile.tempdir = _ROOT
_extra_roots: list = []


def _anchors() -> dict:
    """pid -> command line of every live anchor_server process (all sessions)."""
    out = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    res = {}
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2 and MARK in parts[1] and parts[0].isdigit() and int(parts[0]) != os.getpid():
            res[int(parts[0])] = parts[1]
    return res


def _ours(cmd: str) -> bool:
    roots = [_ROOT, _ROOT.replace("/private", "", 1)] + _extra_roots
    return any(f"{r.rstrip('/')}/" in cmd for r in roots)


def pytest_configure(config):
    base = getattr(config.option, "basetemp", None)
    if base:
        _extra_roots.append(os.path.realpath(str(base)))


def pytest_sessionfinish(session, exitstatus):
    try:
        bt = session.config._tmp_path_factory.getbasetemp()
        _extra_roots.append(os.path.realpath(str(bt)))
    except Exception:
        pass
    deadline = time.time() + 5
    while True:
        leaked = {p: c for p, c in _anchors().items() if _ours(c)}
        if not leaked or time.time() > deadline:
            break
        time.sleep(0.5)
    for p in leaked:
        try:
            os.kill(p, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if leaked:
        print(f"\nANCHOR LEAK: {len(leaked)} r3_shared.anchor_server process(es) started by this session were still alive: "
              f"{sorted(leaked)} (killed)")
        session.exitstatus = 1
    shutil.rmtree(_ROOT, ignore_errors=True)
