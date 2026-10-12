"""P1g-2 AuthorityService: lease rule on scripted and random publish/fetch schedules (against an independent model), strict
boundary ticks, MAC verification (known-negative), outage/partition modes, sandbox write denial, close() reveals the key."""
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from r3_shared import authsvc
from r3_shared.authsvc import (AuthorityClient, AuthorityError, AuthorityUnavailable, in_force, start_authority,
                               validate_lease, validate_log, verify_log)
from r3_shared.faultplane import DependencyUnavailable

LEASE = 4


def doc(n):
    return {"version": "t", "n": n}


@pytest.fixture
def svc():
    d = Path(tempfile.mkdtemp(prefix="r3a"))
    p = start_authority(d / "auth", d / "s", lease=LEASE)
    p.closed = False
    yield p
    if not p.closed:
        try:
            p.close()
        except Exception:
            p.proc.kill()
    shutil.rmtree(d, ignore_errors=True)


def test_scripted_lease_rule_pending_publish_and_boundaries(svc):
    c, ctl = svc.client("dep-1"), svc.control()
    d0 = ctl.publish(doc(0))
    ctl.advance(0)
    l = c.fetch()
    assert (l.digest, l.granted_tick, l.lease_until) == (d0, 0, 4) and l.doc == doc(0)
    ctl.advance(3)
    assert c.fetch().lease_until == 7                          # renew: t + LEASE
    info = ctl.publish_info(doc(1))                            # published at 3 while a lease runs to 7 -> pending until 7
    d1 = info["digest"]
    assert info["effective_tick"] == 7 and d1 != d0
    ctl.advance(4)
    l = c.fetch()
    assert l.digest == d0 and l.lease_until == 7              # min(t + LEASE, f)
    ctl.advance(6)
    l = c.fetch()
    assert l.digest == d0 and l.lease_until == 7 and l.valid_at(6) and not l.valid_at(7)   # strict upper bound
    ctl.advance(7)
    l = c.fetch()
    assert l.digest == d1 and (l.granted_tick, l.lease_until) == (7, 11)                    # t >= f -> new digest
    lg = ctl.log()
    assert in_force(lg["versions"], 6) == d0 and in_force(lg["versions"], 7) == d1
    assert [v["effective_tick"] for v in lg["versions"]] == [0, 7]
    assert len(lg["leases"]) == 5 and lg["refused"] == [] and lg["faults"] == []


def test_publish_with_no_outstanding_lease_is_immediate(svc):
    ctl = svc.control()
    ctl.publish(doc(0))
    ctl.advance(10)
    info = ctl.publish_info(doc(1))
    assert info["effective_tick"] == 10
    assert svc.client("d").fetch().digest == info["digest"]


class Model:
    """Independent re-implementation of the P1g-2 rule (list-based, no SQL)."""

    def __init__(self):
        self.versions, self.leases = [], []

    def publish(self, d, p):
        older = [u for (_, dg, _, u) in self.leases if dg != d]
        f = max([p] + older + [v[2] for v in self.versions])
        self.versions.append((d, p, f))

    def fetch(self, t):
        cur = max((v for v in self.versions if v[2] <= t), key=lambda v: (v[2], self.versions.index(v)))
        pend = [v[2] for v in self.versions if v[2] > t]
        until = min([t + LEASE] + pend)
        self.leases.append((None, cur[0], t, until))
        return cur[0], until


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_schedules_match_model(svc, seed):
    rng, ctl, c, m, t = random.Random(seed), svc.control(), svc.client("dep-r"), Model(), 0
    d = authsvc.doc_digest(doc(0))
    ctl.publish(doc(0)); m.publish(d, 0)
    n = 1
    for _ in range(160):
        t += rng.choice([0, 0, 1, 1, 2, 3, 5])
        ctl.advance(t)
        if rng.random() < 0.15:
            n += 1
            dg = ctl.publish(doc(n)); m.publish(dg, t)
        else:
            want = m.fetch(t)
            l = c.fetch()
            assert (l.digest, l.lease_until) == want, (t, l, want)
    lg = ctl.log()
    assert [v["effective_tick"] for v in lg["versions"]] == [v[2] for v in m.versions]


def test_outage_drop_and_reply_lost_modes(svc):
    c, ctl = svc.client("dep-o"), svc.control()
    d0 = ctl.publish(doc(0))
    ctl.outage("dep-o", 2, 4, "drop")
    ctl.outage("dep-o", 6, 8, "reply_lost")
    ctl.advance(1)
    assert c.fetch().digest == d0
    ctl.advance(2)
    with pytest.raises(AuthorityUnavailable) as ei:
        c.fetch()
    assert isinstance(ei.value, DependencyUnavailable) and str(ei.value) == "AUTH" and ei.value.node == "AUTH"
    ctl.advance(4)
    assert c.fetch().granted_tick == 4                         # window is [from, to)
    assert svc.client("other-dep").fetch().granted_tick == 4   # other deployments unaffected
    ctl.advance(7)
    with pytest.raises(AuthorityUnavailable):
        c.fetch()
    lg = ctl.log()
    assert [(r["tick"], r["reason"]) for r in lg["refused"]] == [(2, "outage:drop")]            # drop: only a refused row
    assert [l["granted_tick"] for l in lg["leases"] if l["deployment"] == "dep-o"] == [1, 4, 7]  # reply_lost: lease granted + logged
    assert [(f["kind"], f["mode"]) for f in lg["faults"]] == [("outage", "drop"), ("outage", "reply_lost")]


def test_close_reveals_key_and_macs_verify_known_negative(svc, tmp_path):
    c, ctl = svc.client("dep-m"), svc.control()
    ctl.publish(doc(0))
    for t in (0, 1, 2):
        ctl.advance(t)
        c.fetch()
    closed = svc.close()
    svc.closed = True
    assert len(closed["key_hex"]) == 64 and closed["head"]["leases"] == 3
    assert (Path(svc.auth_dir) / "KEY.revealed").read_text() == closed["key_hex"]
    assert not list(Path(svc.auth_dir).glob("authority.db-*"))      # journal mode DELETE at close (G4-E13)
    v = verify_log(svc.auth_dir)
    assert v["ok"], v["errors"]
    bad = tmp_path / "bad"
    shutil.copytree(svc.auth_dir, bad)
    con = sqlite3.connect(str(bad / "authority.db"))
    con.execute("UPDATE leases SET lease_until=lease_until+1 WHERE seq=2")    # extend a lease without the key
    con.commit(); con.close()
    v = verify_log(bad)
    assert not v["ok"] and any("bad MAC" in e for e in v["errors"]) and any("HEAD.final" in e for e in v["errors"])


def test_server_refuses_to_start_without_dir():
    env = {**os.environ, "PYTHONPATH": str(Path(authsvc.__file__).resolve().parents[1])}
    p = subprocess.run([sys.executable, "-m", "r3_shared.authsvc_server", "--socket", "/tmp/x"], capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode != 0 and "--dir" in p.stderr


def test_start_refuses_dir_with_existing_log(svc):
    with pytest.raises(AuthorityError, match="already holds"):
        start_authority(svc.auth_dir, Path(svc.sock_path).with_name("s2"))


def test_data_plane_has_no_control_ops_and_control_plane_no_fetch(svc):
    from r3_shared.authsvc import _call
    for op in ("publish", "advance", "outage", "log", "close"):
        with pytest.raises(AuthorityError, match="not available on the data plane"):
            _call(svc.sock_path, {"op": op, "doc": {}, "tick": 1, "cmd": {}})
    with pytest.raises(AuthorityError, match="not available on the control plane"):
        _call(svc.ctl_path, {"op": "fetch", "deployment": "d"})
    with pytest.raises(AuthorityError, match="no authority version"):
        svc.client("d").fetch()


def test_sandbox_denies_writes_to_auth_dir_but_socket_works(svc):
    assert shutil.which("sandbox-exec"), "sandbox-exec unavailable: the AuthorityService write-denial cannot be enforced - report to the author"
    svc.control().publish(doc(0))
    real = os.path.realpath(svc.auth_dir)
    child = ("import sys,os\nfrom r3_shared.authsvc import AuthorityClient\nout={}\n"
             "for n,f in (('append_db',lambda:open(os.path.join(sys.argv[1],'authority.db'),'ab').write(b'x')),"
             "('create',lambda:open(os.path.join(sys.argv[1],'evil'),'w').write('x')),"
             "('unlink_db',lambda:os.unlink(os.path.join(sys.argv[1],'authority.db')))):\n"
             "    try: f(); out[n]='ok'\n    except PermissionError: out[n]='PermissionError'\n"
             "out['fetch']=AuthorityClient(sys.argv[2],'dep-s').fetch().granted_tick\nprint(out)\n")
    r = subprocess.run(["sandbox-exec", "-p", f'(version 1)(allow default)(deny file-write* (subpath "{real}"))', sys.executable, "-c", child,
                        real, svc.sock_path], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PYTHONPATH": str(Path(authsvc.__file__).resolve().parents[1])})
    assert r.returncode == 0, r.stderr
    out = eval(r.stdout.strip().splitlines()[-1])
    assert out == {"append_db": "PermissionError", "create": "PermissionError", "unlink_db": "PermissionError", "fetch": 0}, out


def test_require_authority_refuses_without_service(svc):
    assert authsvc.require_authority("exp-h29-001", env={"R3_AUTH_SOCK": svc.sock_path, "R3_AUTH_CTL": svc.ctl_path,
                                                          "R3_AUTH_DIR": svc.auth_dir}) == (svc.sock_path, svc.ctl_path, svc.auth_dir)
    with pytest.raises(AuthorityError, match="requires R3_AUTH_SOCK"):
        authsvc.require_authority("exp-h29-001", env={})
    with pytest.raises(AuthorityError, match="no AuthorityService configured"):
        authsvc.require_authority("exp-h29-dev1", env={})
    with pytest.raises(AuthorityError, match="is not running"):
        authsvc.require_authority("exp-h29-001", env={"R3_AUTH_SOCK": "/tmp/r3-none-sock", "R3_AUTH_CTL": "x", "R3_AUTH_DIR": "y"})


def test_validators_reject_malformed_forms(svc):
    good = {"digest": authsvc.doc_digest(doc(1)), "doc": doc(1), "granted_tick": 0, "lease_until": 4, "mac": "a" * 64}
    assert validate_lease(good).lease_until == 4
    for mutate in ({"extra": 1}, {"granted_tick": True}, {"digest": "b" * 64}, {"lease_until": 0}, {"mac": "zz"}, {"doc": []}):
        with pytest.raises(ValueError):
            validate_lease({**good, **mutate})
    with pytest.raises(ValueError):
        validate_lease({k: v for k, v in good.items() if k != "mac"})
    ctl = svc.control()
    ctl.publish(doc(0)); svc.client("d").fetch()
    lg = ctl.log()
    assert validate_log(lg) is lg
    for mutate in (lambda g: g["leases"][0].update(digest="c" * 64), lambda g: g["versions"][0].update(effective_tick=-1),
                   lambda g: g.update(extra=1), lambda g: g["refused"].append({"seq": 1})):
        bad = json.loads(json.dumps(lg))
        mutate(bad)
        with pytest.raises(ValueError):
            validate_log(bad)


def test_fault_commands_validated_server_side(svc):
    ctl = svc.control()
    with pytest.raises(AuthorityError):
        ctl._c({"op": "outage", "cmd": {"op": "outage", "deployment": "d", "from_tick": 5, "to_tick": 5, "mode": "drop"}})   # empty window
    with pytest.raises(AuthorityError):
        ctl._c({"op": "outage", "cmd": {"op": "outage", "deployment": "d", "target": "WMS", "from_tick": 1, "to_tick": 5, "mode": "drop"}})
    with pytest.raises(AuthorityError):
        ctl._c({"op": "outage", "cmd": {"op": "outage", "deployment": "d", "from_tick": 1, "to_tick": 5, "mode": "slow"}})
