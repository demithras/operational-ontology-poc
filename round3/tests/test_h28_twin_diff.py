"""G4-E26: the twin decision-plane diff is byte-exact on the identical absolute clock: no tick shift, no excluded envelope field."""
import json

from r3_harness.h28.judge import twin_diff


def env(tick=100, digest="e1", status="OK"):
    return json.dumps({"decision": {"tick": tick, "effect_digest": digest, "status": status}, "sig": "x"})


def rec(tick=100, status="OK", version="v", etick=100, digest="e1", wdigest="d"):
    au = {"status": "OK", "body": {"authority_version": version, "tick": tick, "world_seq": 5}}
    return {"start_tick": 100, "world_digest": wdigest,
            "recorder": {"S": [{"request_id": "r", "effect_index": 0, "envelope_text": env(etick, digest)}]},
            "requests": [{"i": 0, "replay": False, "status": status, "reason": None, "authority_used": au}]}


def test_identical_schedule_is_equal():
    assert twin_diff(rec(), rec()) == []


def test_absolute_tick_difference_is_not_masked():
    assert twin_diff(rec(100), rec(114)) == ["req(0, False).authority_used"]
    assert twin_diff(rec(), rec(etick=114)) == ["envelope"]


def test_effect_digest_difference_is_caught():
    assert twin_diff(rec(), rec(digest="e2")) == ["envelope"]


def test_decision_change_still_fails():
    assert twin_diff(rec(), rec(status="DENIED")) == ["req(0, False).status"]
    assert twin_diff(rec(), rec(version="w")) == ["req(0, False).authority_used"]
    assert twin_diff(rec(), rec(wdigest="z")) == ["world"]
