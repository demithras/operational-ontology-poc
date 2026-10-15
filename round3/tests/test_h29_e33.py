"""G5-E33: world_log commit marks are cross-checked against the anchor log and the ExternalWorld ledger, and the world_log itself is watched for
rewrites. Honest oracle-backed fake stays clean; every check has a known-negative (record-level on the honest fake's own raw records)."""
import copy
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from r3_harness.h28.judge import LedgerIndex
from r3_harness.h29 import finalize, judge, runner, wlog
from r3_harness.h29.svcset import SvcSet
from tests.fakes.h29_rig import fake

_cache: dict = {}
NEW_WHATS = {"unanchored_commit", "anchored_without_commit", "committed_effect_missing", "world_log_rewritten"}


def honest():
    if not _cache:
        sv = SvcSet(1)
        try:
            out = Path(tempfile.mkdtemp(prefix="h29e33", dir="/tmp"))
            pre = runner.run_variant(str(sv.root), fake("FakeHonestG5"), "fake", out, "exp-h29-fakes-dev-1", 2911, 24, 4, 4, 1, extra_paths=["."], in_process=True)
            closes = sv.close()
            _cache["J"] = finalize.judge_all(out, sv.root, 1, pre, closes)
        finally:
            sv.cleanup()
    return _cache["J"]


def ctx_of(J, anchor=None, merged=None):
    sv = J["services"]
    return judge.Ctx(LedgerIndex(merged or sv["merged"]), anchor if anchor is not None else sv["anchor"], None, sv["anchor_seq"], workers=1)


def whats(row):
    return sorted(d.get("what") for d in row["classes"].get("recovery_divergence", []) if d.get("what") in NEW_WHATS)


def committed_raw(J, need_effect=False):
    led = LedgerIndex(J["services"]["merged"])
    for R in J["raws"]:
        if R["stratum"] == "bnd" or not R.get("world") or not R["world"]["marks"]:
            continue
        if need_effect and not led.dep_ledger(R["dep"])["effects"]:
            continue
        return R
    raise AssertionError("no committed sequence in the honest run")


def test_honest_fake_is_clean_and_every_sequence_observed_the_world_log():
    J = honest()
    for r in J["rows"]:
        assert not whats(r) and "forbidden_effect" not in r["classes"], (r["seq"], r["classes"])
        assert "world_log_unobserved" not in r["harness"]
    envs = [R for R in J["raws"] if R["stratum"] != "bnd"]
    assert envs and all(R["wl"] and R["wl"][-1]["where"] == "end" and not R["wl"][-1]["gap"] for R in envs)
    assert any(o["where"] == "rc1" for R in envs for o in R["wl"])                     # RC1 reads happened and prefixes were compared
    assert any(o.get("prefix_changed") is False for R in envs for o in R["wl"])
    assert sum(len(r["classes"].get("recovery_divergence", [])) for r in J["rows"]) == 0


def test_a_forged_commit_mark_is_unanchored_and_forbidden():
    J = honest()
    R = copy.deepcopy(committed_raw(J))
    R["world"]["marks"].append({"seq": 9999, "tick": 3, "writer": "x", "data": {"request_id": "r-forged", "authority_version": 0, "kind": "commit"}})
    row = judge.judge_seq(R, ctx_of(J))
    assert "unanchored_commit" in whats(row) and any(d["rid"] == "r-forged" for d in row["classes"]["forbidden_effect"])


def test_a_deleted_anchor_entry_is_an_unanchored_commit():
    J = honest()
    R = committed_raw(J)
    rid = R["world"]["marks"][0]["data"]["request_id"]
    anchor = {k: {x for x in v if x != (R["stream"], rid)} for k, v in J["services"]["anchor"].items()}
    row = judge.judge_seq(R, ctx_of(J, anchor))
    assert [d["rid"] for d in row["classes"]["recovery_divergence"] if d["what"] == "unanchored_commit"] == [rid]


def test_an_anchored_ok_without_a_commit_mark():
    J = honest()
    R = copy.deepcopy(committed_raw(J))
    rid = R["world"]["marks"][0]["data"]["request_id"]
    R["world"]["marks"] = [m for m in R["world"]["marks"] if m["data"]["request_id"] != rid]
    assert any(e.get("rid") == rid and (e.get("res") or {}).get("status") == "OK" for e in R["events"] if e["k"] in ("request", "redeliver"))
    row = judge.judge_seq(R, ctx_of(J))
    assert "anchored_without_commit" in whats(row)
    assert "unanchored_commit" not in whats(row)


def test_an_effect_row_without_a_commit_mark_is_forbidden():
    J = honest()
    R = copy.deepcopy(committed_raw(J, need_effect=True))
    led = LedgerIndex(J["services"]["merged"]).dep_ledger(R["dep"])
    rid = led["effects"][0]["correlation"].rpartition("#")[0]
    R["world"]["marks"] = [m for m in R["world"]["marks"] if m["data"]["request_id"] != rid]
    row = judge.judge_seq(R, ctx_of(J))
    assert any(d.get("rid") == rid and "without a commit mark" in d.get("why", "") for d in row["classes"]["forbidden_effect"])


def test_a_committed_intent_never_dispatched_is_committed_effect_missing(monkeypatch):
    """G5-E34 (b): with the row cut the oracle itself computes RECONCILED_FAILED, which E33(c) exempts. This negative therefore forces the oracle
    state to PENDING (a committed intent, healed system, no row, no attempt): the check must still fire."""
    from r3_harness.h29 import judge_ext
    real = judge_ext.eval_outcomes

    def pending(*a, **k):
        oc = real(*a, **k)
        oc["oracle"] = {key: ("PENDING",) + tuple(v[1:]) for key, v in oc["oracle"].items()}
        return oc
    monkeypatch.setattr(judge_ext, "eval_outcomes", pending)
    J = honest()
    R = committed_raw(J, need_effect=True)
    assert any(e["k"] == "rc2" for e in R["events"]), "the picked sequence has no RC2"
    sv = J["services"]["merged"]
    dep_rows = LedgerIndex(sv).dep_ledger(R["dep"])["effects"]
    corr = dep_rows[0]["correlation"]
    cut = {**sv, "effects": [r for r in sv["effects"] if r.get("correlation") != corr], "audit": [r for r in sv["audit"] if r.get("correlation") != corr],
           "unverified": [r for r in sv.get("unverified", []) if r.get("correlation") != corr and (r.get("claim") or {}).get("correlation") != corr]}
    row = judge.judge_seq(R, ctx_of(J, merged=cut))
    got = [d for d in row["classes"].get("recovery_divergence", []) if d.get("what") == "committed_effect_missing"]
    assert got and got[0]["rid"] == corr.rpartition("#")[0], row["classes"]


def test_honest_ledger_has_no_committed_effect_missing_on_any_rc2_sequence():
    J = honest()
    assert any(e["k"] == "rc2" for R in J["raws"] if R["stratum"] != "bnd" for e in R["events"])
    assert not [r["seq"] for r in J["rows"] if "committed_effect_missing" in whats(r)]


def _run_stub():
    return SimpleNamespace(t=7)


def test_wlog_detects_a_rewritten_prefix_and_a_seq_gap():
    rows = [{"seq": i, "tx": i, "kind": "mark", "ref": "commit", "data": {"request_id": f"r{i}"}} for i in (1, 2, 3)]
    r = _run_stub()
    assert wlog.observe_rows(r, "rc1", rows)["prefix_changed"] is None
    ok = wlog.observe_rows(r, "end", rows + [{"seq": 4, "tx": 4, "kind": "mark", "ref": "commit", "data": {}}])
    assert ok["prefix_changed"] is False and ok["gap"] is None
    rw = copy.deepcopy(rows)
    rw[0]["data"]["request_id"] = "tampered"
    r2 = _run_stub()
    wlog.observe_rows(r2, "rc1", rows)
    assert wlog.observe_rows(r2, "end", rw)["prefix_changed"] is True
    r3 = _run_stub()
    wlog.observe_rows(r3, "rc1", rows)
    assert wlog.observe_rows(r3, "end", rows[:2])["prefix_changed"] is True                  # shortened log
    assert wlog.observe_rows(_run_stub(), "end", [rows[0], rows[2]])["gap"] == {"index": 1, "seq": 3, "expected": 2}
    assert wlog.observe_rows(_run_stub(), "end", rows[1:])["gap"] == {"index": 0, "seq": 2, "expected": 1}


def test_a_rewritten_world_log_is_world_log_rewritten_and_a_missing_observation_is_a_harness_row():
    J = honest()
    R = copy.deepcopy(committed_raw(J))
    R["wl"][-1]["prefix_changed"] = True
    row = judge.judge_seq(R, ctx_of(J))
    assert "world_log_rewritten" in whats(row)
    R2 = copy.deepcopy(committed_raw(J))
    R2["wl"][-1]["gap"] = {"index": 1, "seq": 5, "expected": 2}
    assert "world_log_rewritten" in whats(judge.judge_seq(R2, ctx_of(J)))
    R3 = copy.deepcopy(committed_raw(J))
    del R3["wl"]
    assert "world_log_unobserved" in judge.judge_seq(R3, ctx_of(J))["harness"]
    assert "world_log_unobserved" in judge.BLOCKING


def test_b4_store_loss_is_not_a_world_log_finding():
    J = honest()
    for R in J["raws"]:
        if R["stratum"] == "bnd":
            continue
        R = copy.deepcopy(R)
        R["world"], R["wl"] = None, [{"where": "end", "t": 1, "error": "gone"}]
        assert not whats(judge.judge_seq(R, ctx_of(J)))
        return
    pytest.fail("no sequence")
