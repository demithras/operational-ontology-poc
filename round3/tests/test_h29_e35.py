"""G5-E35 judge checks B1-B8: each has a known-negative that goes red and a proof that the honest oracle-backed fake stays clean."""
import copy
import tempfile
from pathlib import Path

from r3_harness.h28.judge import LedgerIndex
from r3_harness.h29 import finalize, judge, judge_fin, runner
from r3_harness.h29.svcset import SvcSet
from tests.fakes.h29_rig import fake
from tests.test_h29_e34 import ctx_for, env_000192

_cache: dict = {}


def honest():
    if not _cache:
        sv = SvcSet(1)
        try:
            out = Path(tempfile.mkdtemp(prefix="h29e35", dir="/tmp"))
            pre = runner.run_variant(str(sv.root), fake("FakeHonestG5"), "fake", out, "exp-h29-fakes-dev-1", 2911, 24, 4, 4, 1, extra_paths=["."], in_process=True)
            closes = sv.close()
            _cache["J"] = finalize.judge_all(out, sv.root, 1, pre, closes)
            _cache["pre"] = pre
        finally:
            sv.cleanup()
    return _cache["J"]


def ctx_of(J, anchor=None, anchor_seq=None):
    sv = J["services"]
    return judge.Ctx(LedgerIndex(sv["merged"]), anchor if anchor is not None else sv["anchor"], None, anchor_seq if anchor_seq is not None else sv["anchor_seq"], workers=1)


def hits(row, cls, what=None):
    return [d for d in row["classes"].get(cls, []) if what is None or d.get("what") == what]


def raw_with(J, pred):
    for R in J["raws"]:
        if R["stratum"] != "bnd" and pred(R):
            return R
    raise AssertionError("no sequence of the honest run matches")


# ---- B1 redelivery_decision_changed ----------------------------------------------------------------------------------------------------------------
def test_b1_honest_redeliveries_return_the_original_decision():
    J = honest()
    assert not [r["seq"] for r in J["rows"] if hits(r, "recovery_divergence", "redelivery_decision_changed")]
    assert any(e.get("tag") == "rc2_redeliver" for R in J["raws"] for e in R["events"])


def test_b1_a_changed_rc2_redelivery_status_is_flagged_and_enters_the_ratio():
    R = env_000192()
    base = judge.judge_seq(R, ctx_for(R))
    assert not hits(base, "recovery_divergence", "redelivery_decision_changed")
    R2 = copy.deepcopy(R)
    e = next(x for x in R2["events"] if x.get("tag") == "rc2_redeliver" and x["rid"] == "r002")
    e["res"] = {"status": "DENIED", "body": {"reason": "authority"}}
    row = judge.judge_seq(R2, ctx_for(R2))
    d = hits(row, "recovery_divergence", "redelivery_decision_changed")
    assert d and d[0]["rid"] == "r002" and d[0]["original"] == ["OK", None] and d[0]["got"] == ["DENIED", "authority"]
    assert row["recovery_checks"][0] - row["recovery_checks"][1] == base["recovery_checks"][0] - base["recovery_checks"][1] + 1


def test_b1_unavailable_at_rc2_is_a_change_and_a_tamper_sequence_is_exempt():
    R = env_000192()
    e = next(x for x in R["events"] if x.get("tag") == "rc2_redeliver" and x["rid"] == "r002")
    e["res"] = {"status": "UNAVAILABLE", "body": {"reason": "idempotency_record_missing"}}
    assert hits(judge.judge_seq(R, ctx_for(R)), "recovery_divergence", "redelivery_decision_changed")
    R["events"].insert(5, {"k": "tamper", "n": 99, "t": 3, "what": "x"})
    assert not hits(judge.judge_seq(R, ctx_for(R)), "recovery_divergence", "redelivery_decision_changed")      # R27-5 applies instead (F8)


# ---- B2 outcome clause ----------------------------------------------------------------------------------------------------------------------------
def test_b2_honest_fake_has_no_outcome_progress_loss_and_a_non_success_outcome_is_one():
    J = honest()
    op = lambda r: r.get("outcome_progress") or {"checked": 0, "lost": []}      # noqa: E731
    assert sum(op(r)["checked"] for r in J["rows"]) > 0 and not [r["seq"] for r in J["rows"] if op(r)["lost"]]
    seq = next(r["seq"] for r in J["rows"] if op(r)["checked"])
    R = copy.deepcopy(next(R for R in J["raws"] if R["seq"] == seq))
    for e in R["events"]:
        if e["k"] == "reconcile" and e.get("res") and e["res"]["status"] == "OK":
            for o in e["res"]["body"].get("outcomes", []):
                o["state"] = "PENDING"
    row = judge.judge_seq(R, ctx_of(J))
    assert row["outcome_progress"]["lost"], row["outcome_progress"]


# ---- B3 scope of E33(c) ------------------------------------------------------------------------------------------------------------------------------
def test_b3_byzantine_adapter_sequences_are_not_judged_by_committed_effect_missing():
    from r3_harness.h29 import judge_wl
    I = {"correlation": "r1#0", "effect_index": 0, "system": "MES", "operation": "o", "target": "t", "payload_digest": "x"}

    def run(byz):
        R = {"world": {"marks": [{"seq": 7, "tick": 19, "data": {"request_id": "r1"}}]}, "stream": None, "seq_def": {"byz": byz}}
        row = {"classes": {}, "harness": []}
        judge_wl.check_marks(R, None, row, [{"k": "rc2"}], {"effects": [], "audit": [], "unverified": []}, {"r1": [I]}, {"oracle": {("r1", 0): ("PENDING", "full", [], "W")}})
        return hits(row, "recovery_divergence", "committed_effect_missing")
    assert run(None) and not run({"mode": "x"})


# ---- B4 absent == hidden --------------------------------------------------------------------------------------------------------------------------------
def test_b4_hidden_object_reply_must_equal_the_absent_object_reply():
    J = honest()
    R = copy.deepcopy(raw_with(J, lambda R: any(e["k"] == "read" and e["operation"] == "get" and (e.get("res") or {}).get("status") == "INVALID" for e in R["events"])))
    assert not [r for r in J["rows"] if r["seq"] == R["seq"] and r["classes"].get("disclosure_leak")]
    e = next(e for e in R["events"] if e["k"] == "read" and e["operation"] == "get" and (e.get("res") or {}).get("status") == "INVALID")
    e["res"] = {"status": "DENIED", "body": {"reason": "forbidden"}}
    row = judge.judge_seq(R, ctx_of(J))
    assert any("absent-object" in str(d.get("why")) for d in row["classes"].get("disclosure_leak", [])), row["classes"]


# ---- B5 / B6 --------------------------------------------------------------------------------------------------------------------------------------------
def test_b5_ok_under_anchor_reply_lost_needs_the_anchor_entry_at_the_reply():
    J = honest()
    R = copy.deepcopy(raw_with(J, lambda R: R.get("stream") and any(e["k"] == "request" and (e.get("res") or {}).get("status") == "OK" and "anchor_head_at_reply" in e for e in R["events"])))
    e = next(e for e in R["events"] if e["k"] == "request" and (e.get("res") or {}).get("status") == "OK" and "anchor_head_at_reply" in e)
    R["anchor"] = {**(R.get("anchor") or {}), "windows": [*(R.get("anchor") or {}).get("windows", []), {"node": "ANCHOR", "mode": "reply_lost", "from_tick": e["t"], "to_tick": e["t"] + 1}]}
    ok = judge.judge_seq(R, ctx_of(J))
    assert not [d for d in ok["classes"].get("misclassified_dependency_failure", []) if d.get("rid") == e["rid"]], ok["classes"]       # honest: anchored at the reply
    sv = J["services"]
    seqs = {k: {kk: [x for x in v if x > e["anchor_head_at_reply"]] for kk, v in d.items()} for k, d in sv["anchor_seq"].items()}
    bad = judge.judge_seq(R, ctx_of(J, anchor_seq=seqs))
    assert [d for d in bad["classes"].get("misclassified_dependency_failure", []) if d.get("rid") == e["rid"]], bad["classes"]


def _approve_raw(J):
    return raw_with(J, lambda R: R.get("stream") and any(e["k"] == "approve" and (e.get("res") or {}).get("status") == "OK" and "anchor_head_at_reply" in e for e in R["events"]))


def test_b6_honest_approvals_are_classified_and_clean():
    J = honest()
    assert any(q.get("k") == "approve" for r in J["rows"] for q in r["req"])
    assert not [r["seq"] for r in J["rows"] if r["classes"].get("unanchored_ack") or r["classes"].get("misclassified_dependency_failure")]


def test_b6_an_approval_ack_without_an_anchor_entry_and_an_ok_during_an_auth_outage_are_flagged():
    J = honest()
    R = copy.deepcopy(_approve_raw(J))
    e = next(e for e in R["events"] if e["k"] == "approve" and (e.get("res") or {}).get("status") == "OK" and "anchor_head_at_reply" in e)
    none_after = {k: {kk: [x for x in v if not (e["anchor_head_before"] < x <= e["anchor_head_at_reply"])] for kk, v in d.items()} for k, d in J["services"]["anchor_seq"].items()}
    assert judge.judge_seq(R, ctx_of(J, anchor_seq=none_after))["classes"].get("unanchored_ack")
    R["auth"]["faults"] = [*R["auth"]["faults"], {"deployment": R["dep"], "kind": "outage", "from_tick": e["t"], "to_tick": e["t"] + 1, "mode": "drop"}]
    row = judge.judge_seq(R, ctx_of(J))
    assert any(d.get("kind") == "approve" for d in row["classes"].get("misclassified_dependency_failure", [])), row["classes"]


# ---- B7 invalid_if (a) from the fault plane's record ------------------------------------------------------------------------------------------------
def test_b7_an_armed_crash_point_counts_as_fired_only_after_a_host_death_not_forced_by_the_harness():
    R = {"auth": {"faults": [], "refused": []}, "anchor": {}, "ext": [], "dep": "d", "harness": []}
    arm = {"k": "crash_armed", "n": 1, "t": 0, "point": "CP1_before_commit", "key": "c001"}

    def fired(*evs):
        return [x for x in judge_fin._injection(R, [arm, *evs], {"audit": [], "unverified": []}, None) if "crash_point" in x][0]
    assert fired()["fired"] == 0
    assert fired({"k": "host_dead", "n": 2, "t": 9, "kill": 9, "forced": True})["fired"] == 0
    f = fired({"k": "host_dead", "n": 2, "t": 9, "kill": 9, "forced": False})
    assert f["fired"] == 1 and f["fired_tick"] == 9


# ---- B8 ExternalWorld close() key + ledger verification ----------------------------------------------------------------------------------------------
def test_b8_ext_verification(tmp_path):
    import json
    row = {"cap_chain": "c", "correlation": "r#0", "system": "S", "target": "t", "payload_digest": "d"}
    led = {"effects": [row], "audit": [{**row, "outcome": "applied"}, {**row, "outcome": "refused"}]}
    (tmp_path / "KEY.revealed").write_text("ab" * 16)
    (tmp_path / "HEAD.final").write_text(json.dumps({"effects": 1, "audit": 2}))
    assert finalize.verify_ext(tmp_path, led)["ok"]
    assert not finalize.verify_ext(tmp_path, {**led, "effects": []})["ok"]                                    # ledger differs from HEAD.final
    (tmp_path / "KEY.revealed").unlink()
    assert "key not revealed" in finalize.verify_ext(tmp_path, led)["errors"]
    (tmp_path / "KEY.revealed").write_text("ab" * 16)
    assert not finalize.verify_ext(tmp_path, led, {"root_key_hex": "cd" * 16})["ok"]
    assert not finalize.verify_ext(tmp_path, {"effects": [row], "audit": [{**row, "outcome": "refused"}, {**row, "outcome": "refused"}]})["ok"]   # effect without an applied audit row
