"""End to end over REAL services and a spawned host: start (auth, anchor, ExternalWorld) -> publish -> lease -> fault -> kill ->
resume -> close; every service closes and no process of this test is left behind (conftest leak hygiene backs this up)."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from r3_shared.anchor import start_anchor, verify_anchor_log
from r3_shared.authsvc import in_force, verify_log
from r3_shared.extsystems import load_systems
from r3_shared.extworld import start_external
from r3_shared.host import HostDead
from r3_shared.recovery import validate_recovery_view
from r3_shared.variant import g5_call
from tests.p1g_util import Rig, token

PUT = {"type": "Part", "key": "P1"}


def test_start_publish_lease_fault_kill_resume_close(tmp_path):
    d = Path(tempfile.mkdtemp(prefix="r3e"))
    sysp = d / "systems.json"
    sysp.write_text(json.dumps(load_systems("manufacturing")))
    ext = start_external(d / "ext", sysp, d / "e.sock")
    anc = start_anchor(d / "anchor", d / "a.sock", control=True)
    rig = Rig(anchor=anc.sock_path, history=True)
    try:
        actl, nctl, tok = rig.auth.control(), anc.control(), token()
        px = rig.start()
        assert px.direct(tok, "put", PUT, None, "r1").body == {}                      # lease granted at tick 0 (until 4), anchored
        d1 = actl.publish(rig.doc(1))                                                 # published at 0 while a lease runs to 4 -> pending until 4
        assert [v["effective_tick"] for v in actl.log()["versions"]] == [0, 4]
        for t in (1, 2, 3):
            actl.advance(t); nctl.advance(t); ext.client().advance(t); px.advance(t)
            assert px.direct(tok, "put", PUT, None, f"t{t}").status == "OK"          # renewals keep returning the OLD digest until f
        actl.advance(4); nctl.advance(4); px.advance(4)
        actl.outage("dep-g5", 4, 8, "drop")
        r = px.direct(tok, "put", PUT, None, "blocked")
        assert (r.status, r.body) == ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "AUTH"})   # lease_until 4: strict
        nctl.partition(rig_stream(rig), 4, 6, "drop")
        actl.advance(8); px.advance(8); nctl.advance(5)
        nctl.advance(6)
        px.arm("CP2_after_commit", "r-die")
        with pytest.raises(HostDead):
            px.direct(tok, "put", PUT, None, "r-die")
        actl.advance(9)
        px2 = rig.start(resume=True, tick=9)
        validate_recovery_view(g5_call(px2, "recovery_view"))
        assert px2.direct(tok, "put", PUT, None, "r-die").body.get("replayed") is True    # redelivery after hard restart: no second commit
        assert rig.commits().count("r-die") == 1
        lg = actl.log()
        assert in_force(lg["versions"], 3) != in_force(lg["versions"], 4) == d1
        assert any(l["digest"] == d1 for l in lg["leases"])
        assert [f["mode"] for f in lg["faults"]] == ["drop"] and lg["refused"][0]["reason"] == "outage:drop"
        for h in rig.hosts:
            if h.alive:
                h.close()
        closed = rig.auth.close()                                                     # key revealed, journal removed, MACs verify
        v = verify_log(rig.auth.auth_dir, closed["key_hex"])
        assert v["ok"], v["errors"]
        rig.auth = None
    finally:
        rig.cleanup()
        ahead = anc.close()
        ext.close()
        assert verify_anchor_log(d / "anchor", expected_head=ahead["head"])["ok"]


def rig_stream(rig):
    import sqlite3
    con = sqlite3.connect(str(rig.root / "hist.db"))
    try:
        return con.execute("SELECT value FROM hist WHERE key='meta/stream'").fetchone()[0].decode()
    finally:
        con.close()
