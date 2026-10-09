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
# Shard file list (scripts/run_tests_sharded.sh). Popped so nested pytest sessions / child processes don't inherit it.
_SHARD_LIST = os.environ.pop("R3_SHARD_FILES", None)


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


def pytest_collection_modifyitems(config, items):
    """Sharding (scripts/run_tests_sharded.sh): the R3_SHARD_FILES env var names a file with one test-file path per line (relative to
    round3/). Every shard collects the WHOLE suite exactly like a serial run (same conftest/import order) and deselects
    items outside its list; collecting per-file args instead made fixtures from tests/conventional/conftest.py vanish."""
    lst = _SHARD_LIST
    if not lst:
        return
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mine = {os.path.join(root, l.strip()) for l in open(lst) if l.strip()}
    keep = [i for i in items if str(i.path) in mine]
    drop = [i for i in items if str(i.path) not in mine]
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep


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
        for p, c in sorted(leaked.items()):
            print(f"  leaked {p}: {c[-160:]}")
        session.exitstatus = 1
    shutil.rmtree(_ROOT, ignore_errors=True)
