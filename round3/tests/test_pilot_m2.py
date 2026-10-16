"""H30 pilot step 0 repro, defect M2: subscribe/poll must be decided under the authority version in force (AUTH lease gate).
Scenario (G5/H29 mode, REAL AuthorityService + anchor, both variants): planner-1 subscribes to WorkOrder while authorised to read it;
a narrowing authority version (drops the disclosure rule m-planner-wo) is published and comes into force; a legitimate commit to
WorkOrder:WO-42 lands in the world log; planner-1 polls BEFORE any other governed call. Correct: no event carries WorkOrder props.
The commit is written straight to the world store (an independent writer; a governed call through the same service would itself
adopt the new lease and mask the gap). Expected: RED on conventional, GREEN on paladin."""
import copy
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
for sub in ("paladin", "conventional"):
    sys.path.insert(0, str(HERE / sub))

import conv_g5_util as CV  # noqa: E402
import g5_rig as PL  # noqa: E402

WO, NEW_START = "WorkOrder:WO-42", 777


def narrowed_disclosure(doc):
    d = copy.deepcopy(doc)
    n = len(d["disclosure"]["rules"])
    d["disclosure"]["rules"] = [r for r in d["disclosure"]["rules"] if r["id"] != "m-planner-wo"]
    assert len(d["disclosure"]["rules"]) == n - 1
    return d


class Side:
    def __init__(self, name, tmp_path):
        self.name = name
        if name == "paladin":
            self.rig = PL.G5Rig(external=False)
            self.dep, self.actl, self.v0 = self.rig.dep, self.rig.actl, self.rig.auth0
        else:
            self.rig = CV.make_g5(tmp_path / "conv")
            self.dep, self.actl, self.v0 = self.rig.dep, self.rig.actl, CV.V0

    def token(self, sub):
        return self.rig.token(sub)

    def tick(self, n):
        self.rig.tick(n)

    def world_write(self):
        h = self.rig.store.handle("seed")
        h.update("WorkOrder", "WO-42", {"plannedStart": NEW_START})
        h.close()

    def head(self):
        r = self.rig.store.reader()
        try:
            return max(x["seq"] for x in r.log())
        finally:
            r.close()

    def close(self):
        if self.name == "paladin":
            self.rig.finish()
        else:
            CV.stop_all()


@pytest.fixture(params=["paladin", "conventional"])
def side(request, tmp_path):
    s = Side(request.param, tmp_path)
    yield s
    s.close()


def _subscribe_while_authorised(s):
    t = s.token("planner-1")
    ro = s.dep.read_object(t, WO)
    assert ro.status == "OK" and "plannedStart" in str(ro.body), ro      # authorised to read T before the narrowing
    sub = s.dep.subscribe(t, {"types": ["WorkOrder"]})
    assert sub.status == "OK", sub
    return t, sub.body["sub"]


def _events_with_protected_props(res):
    assert res.status == "OK", res
    return [e for e in res.body["events"] if e.get("ref", "").startswith("WorkOrder:") or "plannedStart" in e.get("props", {})]


def test_control_without_publish_the_commit_is_delivered_with_its_protected_prop(side):
    """Non-vacuity of the oracle: under the UNCHANGED authority K does receive the plannedStart update (both variants)."""
    t, sid = _subscribe_while_authorised(side)
    cur = side.head()
    side.world_write()
    assert side.head() > cur                                             # the commit really landed after the cursor
    ev = _events_with_protected_props(side.dep.poll(t, sid))
    assert [e["props"].get("plannedStart") for e in ev] == [NEW_START], ev


def test_poll_after_read_grant_removed_emits_no_protected_event(side):
    t, sid = _subscribe_while_authorised(side)
    info = side.actl.publish_info(narrowed_disclosure(side.v0))
    side.tick(10)                                                        # past every outstanding lease: new version in force
    versions = side.actl.log()["versions"]
    assert len(versions) == 2 and versions[-1]["effective_tick"] <= side.rig.clock.now(), (info, versions)   # precondition: publish took effect
    cur = side.head()
    side.world_write()
    assert side.head() > cur                                             # precondition: the legitimate commit landed after the cursor
    # K makes NO other governed call; the very next call is poll
    res = side.dep.poll(t, sid)
    # precondition (checked AFTER the poll so it cannot mask it): under the new authority K really cannot read the object
    assert "plannedStart" not in str(side.dep.read_object(t, WO).body), "narrowing did not remove K's read of WorkOrder"
    ev = _events_with_protected_props(res)
    assert ev == [], f"{side.name}: poll delivered {ev} under the OLD authority after the read grant was removed"
