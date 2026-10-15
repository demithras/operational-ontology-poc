"""G5-E36: every host death is a host_dead event at the point the harness first notices it; a kills entry without one is a blocking harness row."""
import copy
import types

import pytest

from r3_harness.h29 import driver, judge, judge_fin, rc
from r3_shared.host import HostDead
from tests.test_h29_e34 import ctx_for, env_000192


class DeadHost:
    """Host that died after replying (CP6_idle SIGKILL): alive is False by the time the harness looks."""
    alive = False

    def kill(self):
        pass


class LiveThenDead(DeadHost):
    alive = True

    def request(self, *a, **k):
        raise HostDead("gone")


def mk(host):
    r = driver.Run.__new__(driver.Run)
    r.host, r.kills, r.t, r.ev = host, [], 4, []
    r.rec = {"harness": [], "unsupported": 0}
    return r


def deaths(r):
    return [e for e in r.ev if e["k"] == "host_dead"]


def test_no_host_call_records_the_death_once():
    r = mk(DeadHost())
    assert r.call("request", "x") == (None, "no_host")
    assert r.call("read", "x") == (None, "no_host")                       # second call on the same death: no duplicate
    d = deaths(r)
    assert len(d) == 1 and d[0]["forced"] is False and d[0]["kill"] == 4 and d[0]["step"] == "call:request" and len(r.kills) == 1


def test_call_that_meets_the_death_records_it_once():
    r = mk(LiveThenDead())
    assert r.call("request", "x") == (None, "no_reply")
    assert r.call("request", "x") == (None, "no_reply")
    assert len(deaths(r)) == 1


def test_tamper_after_a_death_between_calls_records_host_dead(monkeypatch):
    r = mk(DeadHost())
    monkeypatch.setattr(rc.services, "tamper", lambda *a, **k: {})
    r.hist_path = r.world_path = r.layout = None
    rc.do_tamper(r, {"what": "x"})
    d = deaths(r)
    assert len(d) == 1 and d[0]["forced"] is False and d[0]["step"] == "tamper" and r.kills[0]["kill"] == 4
    assert not r.rec["harness"]


class Stop(Exception):
    pass


def test_resume_after_a_death_between_calls_records_host_dead(monkeypatch):
    r = mk(DeadHost())
    r.work, r.dep = __import__("pathlib").Path("/nonexistent"), "d"
    monkeypatch.setattr(rc.services, "copy_store", lambda *a, **k: (_ for _ in ()).throw(Stop()))
    with pytest.raises(Stop):
        rc.resume(r)
    d = deaths(r)
    assert len(d) == 1 and d[0]["forced"] is False and d[0]["step"] == "resume" and r.kills == [{"kill": 4, "resume": 4}]
    assert not r.rec["harness"]


def test_tick_probe_death_followed_by_tamper_is_still_one_event(monkeypatch):
    r = mk(DeadHost())
    monkeypatch.setattr(rc.services, "tamper", lambda *a, **k: {})
    r.hist_path = r.world_path = r.layout = None
    r._died(step="tick_probe")
    rc.do_tamper(r, {"what": "x"})
    assert len(deaths(r)) == 1 and len(r.kills) == 1


def armed_record():
    R = copy.deepcopy(env_000192())
    R["kills"] = [{"kill": 3, "resume": 3}]
    last = max(e["n"] for e in R["events"])
    R["events"].append({"k": "crash_armed", "n": last + 1, "t": 2, "point": "CP6_idle", "key": "c001"})
    return R, last + 2


def inj(R):
    return [x for x in judge_fin._injection(R, R["events"], {"audit": [], "unverified": []}, None) if "crash_point" in x]


def test_armed_point_with_a_recorded_death_counts_as_fired_and_a_missing_event_is_a_harness_row():
    R, n = armed_record()
    R["events"].append({"k": "host_dead", "n": n, "t": 3, "kill": 3, "forced": False, "step": "resume"})
    assert inj(R)[-1]["fired"] == 1
    assert "death_unrecorded" not in judge.judge_seq(R, ctx_for(R))["harness"]
    R2 = copy.deepcopy(R)
    R2["events"] = [e for e in R2["events"] if e["k"] != "host_dead"]
    row = judge.judge_seq(R2, ctx_for(R2))
    assert "death_unrecorded" in row["harness"] and "death_unrecorded" in judge.BLOCKING
    assert "injection_miss" not in row["harness"]                          # never reported as "never fired"


def test_known_negative_armed_point_without_any_death_never_fired():
    R, _ = armed_record()
    R["kills"] = []
    assert inj(R)[-1]["fired"] == 0
    assert "death_unrecorded" not in judge.judge_seq(R, ctx_for(R))["harness"]
