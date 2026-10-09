"""Session-level hygiene (G3 fix11): fail the session if anchor_server processes it started are still alive at the end.
A process counts as ours when it was absent at session start and is our child (or an orphan re-parented to init)."""
import os
import signal
import subprocess
import time

MARK = "r3_shared.anchor_server"
_before: set = set()


def _anchors() -> dict:
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True).stdout
    res = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and MARK in parts[2] and parts[0].isdigit() and int(parts[0]) != os.getpid():
            res[int(parts[0])] = int(parts[1])
    return res


def pytest_sessionstart(session):
    _before.clear()
    _before.update(_anchors())


def pytest_sessionfinish(session, exitstatus):
    deadline = time.time() + 5
    while True:
        leaked = {p: pp for p, pp in _anchors().items() if p not in _before and pp in (os.getpid(), 1)}
        if not leaked or time.time() > deadline:
            break
        time.sleep(0.5)
    if leaked:
        for p in leaked:
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
        print(f"\nANCHOR LEAK: {len(leaked)} r3_shared.anchor_server process(es) started by this session were still alive: "
              f"{sorted(leaked)} (killed)")
        session.exitstatus = 1
