"""G5 fix5: the unsynchronized_commit mutant (per-thread world handles) must not make the project git adapter wait on the
committing thread's own write transaction (self-block on a second connection, one busy timeout per call; 300 mutant
scenarios took tens of minutes in the H23 regression run). Deterministic: the busy timeout is shortened to 0.3 s and two
threads meet at a barrier, so the OLD code fails in well under 5 s instead of hanging."""
import threading
import time

import pytest

import r3_shared.world as world

PT = {"threshold": "T-A"}


def _fire(rig, n):
    bar, out = threading.Barrier(n), [None] * n

    def work(i):
        try:
            bar.wait(timeout=10)
            out[i] = rig.dep.direct(rig.token("researcher-1"), "edit_threshold", {**PT, "value": {"min": 11 + i}},
                                    request_id=f"f5-{i}")
        except Exception as exc:  # noqa: BLE001
            out[i] = exc
    ts = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(n)]
    [t.start() for t in ts]
    [t.join(20) for t in ts]
    return out


@pytest.mark.parametrize("mutants", [(), ("unsynchronized_commit",)])
def test_project_commit_from_worker_threads_never_waits_on_own_transaction(make_rig, monkeypatch, mutants):
    monkeypatch.setattr(world, "BUSY_MS", 300)
    rig = make_rig("project", mutants=mutants)
    t0 = time.perf_counter()
    out = _fire(rig, 2)
    elapsed = time.perf_counter() - t0
    assert not any(isinstance(r, Exception) or r is None for r in out), out
    assert any(r.status == "OK" for r in out), [r.status for r in out]
    assert elapsed < 5, f"project commit blocked on its own world transaction ({elapsed:.1f}s)"
