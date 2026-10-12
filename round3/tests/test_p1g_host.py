"""P1g-6 host process: spawn only, SIGKILL at crash points CP1/CP2/CP3/CP6/CP8 observed from the parent, resume in a NEW process,
A/B byte-equal views from copies, module-level cache survives a cooperative crash() but never a host kill, CanonicalStateLost."""
import ast
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from r3_shared import faultplane, host
from r3_shared.anchor import AnchorClient, start_anchor
from r3_shared.clock import LogicalClock
from r3_shared.faultplane import CanonicalStateLost, DependencyUnavailable
from r3_shared.host import DeploymentProxy, HostDead
from r3_shared.recovery import canon_json, validate_recovery_view
from r3_shared.variant import AuthorityBinding, g5_call
from tests.p1g_util import FAKE, ROUND3, STALE, Rig, token

PUT = {"type": "Part", "key": "P1"}


@pytest.fixture
def rig():
    r = Rig()
    yield r
    r.cleanup()


def alive(pid):
    return subprocess.run(["ps", "-p", str(pid), "-o", "pid="], capture_output=True, text=True).stdout.strip() != ""


def test_spawn_only_fresh_interpreter(rig):
    assert host.START_METHOD == "spawn"
    src = Path(host.__file__).read_text()
    tree = ast.parse(src)
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "os.fork" not in calls and not any("multiprocessing" in c for c in calls)
    px = rig.start()
    cmd = subprocess.run(["ps", "-p", str(px.pid), "-o", "ppid=,command="], capture_output=True, text=True).stdout
    assert f" -m r3_shared.host " in cmd and "--workdir" in cmd and int(cmd.split()[0]) == os.getpid()
    assert px.pid != os.getpid()
    assert px.advance(5) == 5 and g5_call(px, "dependency_status") == {"AUTH": "UNKNOWN"}


def test_no_import_time_temp_dirs():
    src = Path(host.__file__).read_text()
    for n in ast.parse(src).body:    # module level statements only
        assert "mkdtemp" not in ast.unparse(n) or isinstance(n, (ast.FunctionDef, ast.ClassDef))


@pytest.mark.parametrize("point,committed", [("CP1_before_commit", False), ("CP2_after_commit", True)])
def test_cp1_cp2_sigkill_observed_from_world_reader(rig, point, committed):
    px = rig.start()
    tok = token()
    assert px.direct(tok, "put", PUT, None, "r-ok").status == "OK"
    px.arm(point, "r-boom")
    with pytest.raises(HostDead):
        px.direct(tok, "put", PUT, None, "r-boom")                # in-flight reply is `no_reply`
    assert px.proc.wait(30) == -9
    assert not alive(px.pid)                                      # reaped: no zombie, no process
    assert rig.commits() == (["r-ok", "r-boom"] if committed else ["r-ok"])   # SQLite durability: CP2 keeps the row, CP1 has none
    with pytest.raises(HostDead):
        px.direct(tok, "put", PUT, None, "r-x")


def test_unarmed_and_wrong_key_never_fire_and_arming_fires_once(rig):
    px = rig.start()
    tok = token()
    px.arm("CP2_after_commit", "someone-else")
    for i in range(3):
        assert px.direct(tok, "put", PUT, None, f"r{i}").status == "OK"
    assert px.alive and rig.commits() == ["r0", "r1", "r2"]


def test_cp6_idle_dies_between_calls_after_the_reply(rig):
    px = rig.start()
    tok = token()
    px.arm("CP6_idle", "r-idle")
    assert px.direct(tok, "put", PUT, None, "r-idle").status == "OK"     # the reply is delivered ...
    px.proc.wait(30)                                                       # ... then the host is gone
    assert px.proc.returncode == -9 and rig.commits() == ["r-idle"]
    with pytest.raises(HostDead):
        px.direct(tok, "put", PUT, None, "r-next")


def test_cp3_after_anchor_append_and_resume_in_new_process():
    d = Path(tempfile.mkdtemp(prefix="r3h"))
    ap = start_anchor(d / "anchor", d / "s")
    r = Rig(with_auth=False, anchor=ap.sock_path, history=True)
    try:
        px, tok = r.start(), token()
        assert px.direct(tok, "put", PUT, None, "r1").status == "OK"
        px.arm("CP3_after_anchor_append", "r2")
        with pytest.raises(HostDead):
            px.direct(tok, "put", PUT, None, "r2")
        px.proc.wait(30)
        assert AnchorClient(ap.sock_path).lookup(px_stream(r), "r2") is not None     # anchored, ack never sent
        assert r.commits() == ["r1", "r2"]
        px2 = r.start(resume=True)                                                    # NEW process over the same stores
        assert px2.pid != px.pid and px2.alive
        assert px2.direct(tok, "put", PUT, None, "r1").body.get("replayed") is True      # redelivery after resume: the ledger survived
        assert px2.direct(tok, "put", PUT, None, "r2").body.get("replayed") is True      # r2 was anchored+committed before the kill
        assert r.commits() == ["r1", "r2"]
    finally:
        r.cleanup()
        ap.close()
        shutil.rmtree(d, ignore_errors=True)


def px_stream(r):
    import sqlite3
    con = sqlite3.connect(str(r.root / "hist.db"))
    try:
        return con.execute("SELECT value FROM hist WHERE key='meta/stream'").fetchone()[0].decode()
    finally:
        con.close()


def test_cp8_first_dispatch_after_resume_and_lease_fetch_after_resume(rig):
    px, tok = rig.start(), token()
    assert px.direct(tok, "put", PUT, None, "r1").status == "OK"
    px.kill()
    px2 = rig.start(resume=True, tick=1)
    px2.arm("CP8_during_recovery", host.CP8_KEY)
    with pytest.raises(HostDead):
        px2.dispatch_pending()
    px2.proc.wait(30)
    px3 = rig.start(resume=True, tick=1)
    assert px3.dispatch_pending().status == "OK"                                       # fires once: the next incarnation is unarmed


def test_two_hosts_from_byte_copies_give_identical_views(rig):
    px, tok = rig.start(), token()
    for i in range(4):
        assert px.direct(tok, "put", {"type": "Part", "key": f"P{i}"}, None, f"r{i}").status == "OK"
    px.kill()
    copy = Path(tempfile.mkdtemp(prefix="r3c"))
    shutil.copytree(rig.root / "state", copy / "state")
    for f in rig.root.glob("world.db*"):
        shutil.copy2(f, copy / f.name)
    a, b = rig.start(resume=True, tick=3), rig.start(resume=True, root=copy, tick=3, dep_id="dep-g5-copy")
    va, vb = a.recovery_view(), b.recovery_view()
    validate_recovery_view(va)
    assert canon_json(va) == canon_json(vb) and [c["request_id"] for c in va["committed"]] == ["r0", "r1", "r2", "r3"]
    b.close()
    shutil.rmtree(copy, ignore_errors=True)
    assert alive(a.pid)


def test_resume_refuses_lost_state(rig):
    px = rig.start()
    px.close()
    shutil.rmtree(rig.root / "state")
    with pytest.raises(CanonicalStateLost):
        rig.start(resume=True)
    os.unlink(rig.root / "world.db")
    with pytest.raises(CanonicalStateLost):
        rig.start(resume=True)


def test_dependency_errors_cross_the_pipe_and_lease_survives_kill(rig):
    px, tok = rig.start(), token()
    ctl = rig.auth.control()
    ctl.advance(0)
    assert px.direct(tok, "put", PUT, None, "r1").status == "OK"                      # lease granted at 0 until 4
    ctl.outage("dep-g5", 1, 9, "drop")
    ctl.advance(2); px.advance(2)
    assert px.direct(tok, "put", PUT, None, "r2").status == "OK"                      # inside the lease window
    ctl.advance(4); px.advance(4)
    r = px.direct(tok, "put", PUT, None, "r3")
    assert (r.status, r.body) == ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "AUTH"})
    assert g5_call(px, "dependency_status") == {"AUTH": "DOWN"}
    assert rig.commits() == ["r1", "r2"]


def test_module_cache_survives_cooperative_crash_but_not_host_kill(rig):
    ctl = rig.auth.control()
    ctl.advance(0)
    clock = LogicalClock(0)
    from r3_shared.authsvc import AuthorityClient
    from r3_shared.identity import IdentityProvider
    from r3_shared.world import WorldStore
    from tests.fakes.fake_g5 import FakeStaleCacheVariant
    from tests.p1g_util import AUD, SECRET
    store = WorldStore(rig.root / "inproc.db", clock=clock)
    (rig.root / "ist").mkdir()
    binding = AuthorityBinding(AuthorityClient(rig.auth.sock_path, "dep-inproc"), 4, {})
    dep = FakeStaleCacheVariant().deploy("manufacturing", store.handle_factory(), IdentityProvider(SECRET).verifier(), {}, rig.doc(0), clock,
                                         state_dir=str(rig.root / "ist"), authority_source=binding)
    tok = IdentityProvider(SECRET).issue("alice", AUD, 1000, clock)
    assert dep.direct(tok, "put", PUT, None, "r1").status == "OK"
    clock.advance(10)                                                                  # the lease (until 4) is long expired
    dep.crash()
    dep.restart()                                                                      # cooperative: the module cache survives
    stale = g5_call(dep, "recovery_view")["authority"]["version"]
    assert stale is not None                                                           # the bug is visible in-process ...
    px = rig.start(variant=STALE)
    ctl.advance(0)
    assert px.direct(token(), "put", PUT, None, "h1").status == "OK"
    px.kill()
    ctl.advance(10)
    px2 = rig.start(variant=STALE, resume=True, tick=10)
    assert px2.recovery_view()["authority"]["version"] is None                         # ... and a host kill takes it away
