"""G5-E34: (a) the judge replays committed requests in COMMIT ORDER (world_seq of the commit marks), never in transcript order; (b) E33(c) as written
(terminal RECONCILED_FAILED / admitted in-doubt oracle states are exempt; attempts are indexed by every correlation form the shared ExternalWorld
writes: row correlation, claim.correlation, claim.caveats - r3_shared/extworld_core.py `_claim` l.153-159, `write` l.172-181 / G5-E4)."""
import copy
import json
from pathlib import Path

from r3_harness.h28.judge import LedgerIndex
from r3_harness.h29 import judge, judge_wl

FIX = Path(__file__).parent / "fakes" / "h29_fixtures" / "env-000192.json"
GATED = ("forbidden_effect", "stale_authority_commit", "duplicate_commit")


def env_000192():
    """exp-h29-001r env-000192 raw record (paladin): crash-armed c001 (preregister H-A) committed at world_seq 98 AFTER r002 (edit T-A, seq 95)."""
    R = json.loads(FIX.read_text())
    for e in R["events"]:
        for k in ("anchor_head_before", "anchor_head_at_reply"):
            e.pop(k, None)
    return R


def ctx_for(R):
    return judge.Ctx(LedgerIndex({"effects": [], "audit": []}), {(R["stream"], m["data"]["request_id"]) for m in R["world"]["marks"]}, None, {}, workers=1)


def gated(row):
    return {c: row["classes"][c] for c in GATED if c in row["classes"]}


def test_env_000192_commit_order_replay_has_no_forbidden_effect_and_digest_matches():
    R = env_000192()
    assert [m["data"]["request_id"] for m in sorted(R["world"]["marks"], key=lambda m: m["seq"])] == ["r002", "r003", "c001", "r004"]
    row = judge.judge_seq(R, ctx_for(R))
    assert not gated(row), row["classes"]
    assert "harness_exception" not in row["harness"], row.get("judge_error")
    assert not [d for d in row["classes"].get("recovery_divergence", []) if d.get("what") == "world_divergence"], row["classes"]


def test_known_negative_a_genuinely_forbidden_commit_is_flagged():
    R = env_000192()
    for m in R["world"]["marks"]:
        if m["data"]["request_id"] == "r002":
            m["seq"], m["tick"] = 100, 6                      # r002 now commits AFTER c001's commit (seq 98): T-A is no longer editable
    row = judge.judge_seq(R, ctx_for(R))
    assert any(d["rid"] == "r002" for d in row["classes"].get("forbidden_effect", [])), row["classes"]


def test_duplicate_commit_is_still_flagged_in_commit_order():
    R = env_000192()
    dup = copy.deepcopy([m for m in R["world"]["marks"] if m["data"]["request_id"] == "r003"][0])
    dup["seq"] = 97
    R["world"]["marks"].append(dup)
    row = judge.judge_seq(R, ctx_for(R))
    assert any(d["rid"] == "r003" for d in row["classes"].get("duplicate_commit", [])), row["classes"]


# ---- (b) judge_wl.check_marks, committed_effect_missing ---------------------------------------------------------------------------------------------
# The 8 exp-h29-001r conventional cases (committed class_details of experiments/h29/exp-h29-001r/conventional/fault-sequences.jsonl.gz).
CASES = [("env-000632", "r008", 0, "MES"), ("env-002032", "r008", 0, "NOTIFY"), ("env-002032", "r010", 0, "NOTIFY"), ("env-003392", "r010", 0, "NOTIFY"),
         ("env-003896", "r005", 0, "REGISTRY"), ("env-003896", "r009", 0, "REGISTRY"), ("env-004352", "r010", 0, "MES"), ("env-004352", "r011", 0, "MES")]


def _unverified(rid, idx):
    """What the shared ExternalWorld writes for an `unavailable` refusal: the row attributes nothing (correlation ""), the claim keeps the caveats."""
    cor = f"{rid}#{idx}"
    return {"seq": 530, "tick": 20, "correlation": "", "claim": {"system": "MES", "deployment": "d", "caveats": [["system", "MES"], ["deployment", "d"], ["correlation", cor], ["not_after_tick", 28]]}}


def _check(rid, idx, system, state, unverified=(), audit=()):
    I = {"correlation": f"{rid}#{idx}", "effect_index": idx, "system": system, "operation": "op", "target": "t", "payload_digest": "x"}
    R = {"world": {"marks": [{"seq": 7, "tick": 19, "data": {"request_id": rid}}]}, "stream": None}
    ev = [{"k": "rc2"}]
    dl = {"effects": [], "audit": list(audit), "unverified": list(unverified)}
    oc = {"oracle": {(rid, idx): (state, "full", [], "F")}}
    row = {"classes": {}, "harness": []}
    judge_wl.check_marks(R, None, row, ev, dl, {rid: [I]}, oc)
    return [d for d in row["classes"].get("recovery_divergence", []) if d.get("what") == "committed_effect_missing"]


def test_the_8_exp_h29_001r_cases_do_not_hit():
    for env, rid, idx, system in CASES:
        assert not _check(rid, idx, system, "RECONCILED_FAILED"), env                                   # terminal RECONCILED_FAILED is exempt
        assert not _check(rid, idx, system, "PENDING", unverified=[_unverified(rid, idx)]), env         # the attempt is visible through claim.caveats
        assert not _check(rid, idx, system, "RECONCILED_FAILED", unverified=[_unverified(rid, idx)]), env


def test_each_attempt_form_is_indexed():
    assert not _check("r1", 0, "MES", "PENDING", audit=[{"seq": 1, "correlation": "r1#0"}])
    assert not _check("r1", 0, "MES", "PENDING", unverified=[{"seq": 2, "correlation": "", "claim": {"correlation": "r1#0"}}])
    assert not _check("r1", 0, "MES", "PENDING", unverified=[_unverified("r1", 0)])
    assert not _check("r1", 0, "MES", "UNKNOWN")                                                         # admitted in-doubt state


def test_known_negative_success_or_pending_with_no_row_and_no_attempt_hits():
    assert _check("r1", 0, "MES", "RECONCILED_SUCCESS")
    assert _check("r1", 0, "MES", "PENDING")
    assert _check("r1", 0, "MES", "PENDING", unverified=[_unverified("r9", 0)])                          # an attempt of ANOTHER correlation does not count
