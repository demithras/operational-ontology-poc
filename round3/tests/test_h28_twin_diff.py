"""G4 fix2: twin decision-plane diff compares authority_used ticks relative to the case start (twins run at different absolute ticks)."""
from r3_harness.h28.judge import twin_diff


def rec(start, tick, status="OK", version="v"):
    au = {"status": "OK", "body": {"authority_version": version, "tick": tick, "world_seq": 5}}
    return {"start_tick": start, "world_digest": "d", "recorder": {},
            "requests": [{"i": 0, "replay": False, "status": status, "reason": None, "authority_used": au}]}


def test_same_relative_tick_is_equal():
    assert twin_diff(rec(100, 100), rec(114, 114)) == []


def test_relative_tick_offset_differs():
    assert twin_diff(rec(100, 100), rec(114, 115)) == ["req(0, False).authority_used"]


def test_decision_change_still_fails():
    assert twin_diff(rec(100, 100), rec(114, 114, status="DENIED")) == ["req(0, False).status"]
    assert twin_diff(rec(100, 100), rec(114, 114, version="w")) == ["req(0, False).authority_used"]
