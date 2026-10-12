"""P1g-3 fault plane: every crash point fires exactly once when armed and never when unarmed or for another key; hook sites
(WorldHandle.transaction CP1/CP2, AnchorClient.append CP3, ObservationClient.read CP7) are no-ops unless armed."""
import pytest

from r3_shared import faultplane
from r3_shared.faultplane import CRASH_POINTS, DependencyUnavailable, arm, crashpoint
from r3_shared.world import WorldStore


@pytest.fixture
def fired(monkeypatch):
    log = []
    monkeypatch.setattr(faultplane, "_kill", lambda: log.append("KILL"))
    faultplane.disarm()
    yield log
    faultplane.disarm()


def test_eight_points_exactly_as_frozen():
    assert CRASH_POINTS == ("CP1_before_commit", "CP2_after_commit", "CP3_after_anchor_append", "CP4_adapter_before_apply",
                            "CP5_adapter_after_apply", "CP6_idle", "CP7_reconcile_after_read", "CP8_during_recovery")


@pytest.mark.parametrize("point", CRASH_POINTS)
def test_each_point_fires_once_for_its_key_only(fired, point):
    for p in CRASH_POINTS:
        crashpoint(p, "k")                                   # unarmed: never
    assert fired == []
    arm(point, "k")
    for p in CRASH_POINTS:
        crashpoint(p, "other")                               # wrong key: never
        if p != point:
            crashpoint(p, "k")                               # wrong point: never
    assert fired == []
    crashpoint(point, "k")
    assert fired == ["KILL"]
    crashpoint(point, "k")                                   # armed state is consumed: exactly once
    assert fired == ["KILL"]


def test_arm_is_one_point_at_a_time_and_validated(fired):
    arm("CP1_before_commit", "a")
    arm("CP2_after_commit", "b")
    crashpoint("CP1_before_commit", "a")
    assert fired == []
    crashpoint("CP2_after_commit", "b")
    assert fired == ["KILL"]
    with pytest.raises(ValueError):
        arm("CP9", "x")
    with pytest.raises(ValueError):
        arm("CP1_before_commit", 3)


def _tx(store, rid, fail=False):
    h = store.handle("w")
    try:
        with h.transaction(tag="effect") as tx:
            h.create("Part", rid, {})
            tx.mark("commit", {"request_id": rid, "kind": "direct", "authority_version": "0" * 64})
    finally:
        h.close()


def test_world_hooks_cp1_before_commit_cp2_after_commit(fired, tmp_path):
    store = WorldStore(tmp_path / "w.db")
    _tx(store, "r0")                                         # unarmed
    assert fired == []
    arm("CP1_before_commit", "r1")
    _tx(store, "r1")
    assert fired == ["KILL"]
    arm("CP2_after_commit", "r2")
    _tx(store, "r2")
    assert fired == ["KILL", "KILL"]
    arm("CP2_after_commit", "never-committed")
    _tx(store, "r3")
    assert fired == ["KILL", "KILL"] and faultplane.armed() == ("CP2_after_commit", "never-committed")
    h = store.handle("w")
    h.create("Part", "anon", {})                             # a transaction without a commit mark never matches
    h.close()
    assert fired == ["KILL", "KILL"]


def test_cp3_after_anchor_ack(fired, tmp_path):
    from r3_shared.anchor import start_anchor
    p = start_anchor(tmp_path / "a", tmp_path / "s")
    try:
        c = p.client()
        arm("CP3_after_anchor_append", "d2")
        c.append("st", 1, "d1", "a" * 64)
        assert fired == []
        c.append("st", 2, "d2", "b" * 64)
        assert fired == ["KILL"] and c.lookup("st", "d2") is not None       # killed only after the anchor acknowledged
    finally:
        p.close()


def test_cp7_after_observer_read(fired, tmp_path):
    from r3_shared.extobs import ObservationClient
    from r3_shared.extsystems import load_systems
    from r3_shared.extworld_core import ExternalWorldCore
    core = ExternalWorldCore(tmp_path / "e", load_systems("manufacturing"))
    obs = ObservationClient(str(tmp_path / "e"), core.observer_key("dep"), load_systems("manufacturing"))
    arm("CP7_reconcile_after_read", "r-rec")
    faultplane.set_context_key("r-other")
    obs.read(0)
    assert fired == []
    faultplane.set_context_key("r-rec")
    obs.read(0)
    assert fired == ["KILL"]
    faultplane.set_context_key("")


def test_dependency_unavailable_str_is_node():
    e = DependencyUnavailable("EXT:ERP")
    assert str(e) == "EXT:ERP" and e.node == "EXT:ERP"
    assert faultplane.nodes(["WMS"]) == ("AUTH", "ANCHOR", "OBS", "EXT:WMS")


def test_fault_command_validation_known_negatives():
    ok = {"op": "outage", "deployment": "d", "from_tick": 1, "to_tick": 3, "mode": "drop"}
    assert faultplane.validate_fault_command(ok) is ok
    for bad in ({**ok, "to_tick": 1}, {**ok, "from_tick": True}, {**ok, "mode": "slow"}, {**ok, "op": "kill"}, {**ok, "x": 1},
                {k: v for k, v in ok.items() if k != "mode"}, {**ok, "deployment": ""}, [], {**ok, "from_tick": -1}):
        with pytest.raises(ValueError):
            faultplane.validate_fault_command(bad)
    assert faultplane.in_window([ok], "d", 2) is ok and faultplane.in_window([ok], "d", 3) is None and faultplane.in_window([ok], "e", 2) is None


# ---- fix2: the crash point never returns (no race with COMMIT) ---------------------------------------------------------
_HOT_SCRIPT = r'''
import sys, threading
from r3_shared import faultplane
from r3_shared.world import WorldStore
db, rid = sys.argv[1], sys.argv[2]
stop = False
def busy():
    n = 0
    while not stop:
        n += 1
for _ in range(2):
    threading.Thread(target=busy, daemon=True).start()
h = WorldStore(db).handle("w")
faultplane.arm("CP1_before_commit", rid)
with h.transaction(tag="t") as tx:
    tx.mark("commit", {"request_id": rid, "kind": "k", "authority_version": 1})
print("SURVIVED", flush=True)
'''


def _run_hot(tmp_path, i, kill_impl=None):
    import subprocess
    import sys
    from r3_shared.world import WorldReader
    script = tmp_path / "hot.py"
    script.write_text(_HOT_SCRIPT if kill_impl is None else _HOT_SCRIPT.replace(
        "faultplane.arm(", f"faultplane._kill = {kill_impl}\nfaultplane.arm(", 1))
    db = str(tmp_path / f"w{i}.db")
    env = {**__import__("os").environ, "PYTHONPATH": str(faultplane.ROUND3 / "src")}
    cp = subprocess.run([sys.executable, str(script), db, f"r{i}"], capture_output=True, text=True, env=env, timeout=60)
    r = WorldReader(db)
    try:
        landed = [x for x in r.log() if x["kind"] == "mark" and x["ref"] == "commit"]
    finally:
        r.close()
    return cp.returncode, cp.stdout, len(landed)


def test_crash_point_never_returns_commit_never_lands_under_a_busy_thread(tmp_path):
    bad = [i for i in range(50) if _run_hot(tmp_path, i) != (-9, "", 0)]
    assert bad == []                                          # killed by SIGKILL, nothing after the hook ran, no commit row


def test_a_returning_kill_goes_red(tmp_path):
    """Control (proves the stress test can fail). The pre-fix _kill was `os.kill(getpid(), SIGKILL)` and returned. On this macOS
    box the self-signal lands before kill() returns, so the race the Paladin builder saw (Linux, 8-shard load) is modelled by
    delivering the signal asynchronously: the old-style _kill that returns, with SIGKILL arriving 0.2 s later."""
    old = ("lambda: (__import__('threading').Timer(0.2, lambda: __import__('os').kill(__import__('os').getpid(), 9)).start())")
    runs = [_run_hot(tmp_path, i, old) for i in range(5)]
    assert all(r != (-9, "", 0) for r in runs), runs          # every run passed the crash point and landed its commit


def test_observer_read_log_line_is_written_even_when_the_read_raises(tmp_path):
    """G5-E25: ObservationClient(read_log=...) records every read ATTEMPT before the fault check; default None writes nothing."""
    import json as _json
    from r3_shared.extobs import ObserverFault, ObserverUnavailable, ObservationClient
    from r3_shared.extsystems import load_systems
    from r3_shared.extworld_core import ExternalWorldCore
    core = ExternalWorldCore(tmp_path / "e", load_systems("manufacturing"))
    log = tmp_path / "reads.log"
    key = core.observer_key("dep")
    obs = ObservationClient(str(tmp_path / "e"), key, load_systems("manufacturing"), ObserverFault.unavailable(reads=(1,)), str(log))
    obs.read(4)
    with pytest.raises(ObserverUnavailable):
        obs.read(5)
    assert [_json.loads(x) for x in log.read_text().splitlines()] == [{"n": 0, "watermark": 4}, {"n": 1, "watermark": 5}]
    quiet = ObservationClient(str(tmp_path / "e"), key, load_systems("manufacturing"))
    quiet.read(1)
    assert len(log.read_text().splitlines()) == 2 and not (tmp_path / "e" / "obs_reads.log").exists()
