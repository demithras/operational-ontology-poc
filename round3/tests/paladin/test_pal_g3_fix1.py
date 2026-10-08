"""Gate 3 fix round 1 (errata G3-E14(2), G3-E17, G3-E19, G3-E21; attribution H25-B, H25-E)."""
from g3_rig import G3Rig

EV = ("evaluate_hypothesis", {"hypothesis": "H-A"})


def test_lapse_is_fixed_at_propose_tick_plus_after_not_at_the_recording_transaction(tmp_path):
    r = G3Rig(tmp_path)                       # m-narrow: lapse deny after 4, review window 3
    r.propose("researcher-1", "c1", *EV)
    r.adv(7)                                  # no transaction between tick 0 and tick 7
    # lapse fixed at 0 + 4; window closes at 4 + 3 = 7 -> FINAL deny now (recording at tick 7 would give NOT_FINAL)
    assert r.act("researcher-1", "execute", case="c1").body == {"reason": "case_denied"}


def test_lapse_one_tick_early_is_still_not_final(tmp_path):
    r = G3Rig(tmp_path)
    r.propose("researcher-1", "c1", *EV)
    r.adv(6)
    assert r.act("researcher-1", "execute", case="c1").body == {"reason": "not_final"}


def test_identical_act_replay_returns_the_stored_result_with_zero_effects(tmp_path):
    from test_pal_g3_h25_more import declare  # noqa: PLC0415
    r = G3Rig(tmp_path)
    assert declare(r).status == "OK" and r.judge("agent-draft-1", "d1", "concur").status == "OK"
    kw = dict(emergency="em1", operation="edit_threshold", args={"threshold": "T-A", "value": {"min": 99}})
    first, eff = r.effects_of(lambda: r.act("researcher-1", "act", rid="a0", **kw))
    assert first.status == "OK" and len(eff) == 1
    again, eff2 = r.effects_of(lambda: r.act("researcher-1", "act", rid="a0", **kw))
    assert again.status == "OK" and again.body["effects"] == first.body["effects"] and eff2 == []   # stored result (R5 replay form)
    other = r.act("researcher-1", "act", rid="a0", **{**kw, "args": {"threshold": "T-A", "value": {"min": 98}}})
    assert other.status == "INVALID" and other.body["reason"].startswith("request_id")
