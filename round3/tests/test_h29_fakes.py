"""Known-negative fakes of ORACLE-AND-HARNESS-G5 s10 (never registered): each yields its expected class set on S-env/S-ctrl rows, the
honest oracle-backed fake yields none. Superset tolerance is explicit per fake: R29-7 read literally makes any OK/DENIED answer to a
BLOCKED request a misclassification, which s10's one-line expectations omit (reported to the orchestrator as a frozen-text gap)."""
import copy
import json
import tempfile
from pathlib import Path

import pytest

from r3_harness.h29 import finalize, runner
from r3_harness.h29.svcset import SvcSet
from tests.fakes.h29_rig import fake

N_ENV, N_CTRL, N_BND = 48, 4, 8
# G5-E19: EXACT class set per known-negative fake (S-env/S-ctrl rows). s10's set, plus misclassified_dependency_failure where R29-7 read
# literally also fires (FailOpen, StaleRestart, AckBeforeAnchor), plus - for FailOpen/StaleRestart only - disclosure_leak and
# recovery_divergence, which are observed consequences of serving/committing past the lease (reported to the orchestrator as a gap in s10).
EXPECT = {
    "FakeFailOpenAuth": {"stale_authority_commit", "forbidden_effect", "misclassified_dependency_failure", "disclosure_leak", "recovery_divergence"},
    "FakeStaleRestart": {"stale_authority_after_restart", "stale_authority_commit", "forbidden_effect", "misclassified_dependency_failure",
                         "disclosure_leak", "recovery_divergence"},
    "FakeRandomRecovery": {"recovery_nondeterministic"},
    "FakeDenyOnOutage": {"misclassified_dependency_failure"},
    "FakeDropOutbox": {"recovery_divergence"},
    "FakeAckBeforeAnchor": {"unanchored_ack", "misclassified_dependency_failure"},
    "FakeMisattributes": {"misclassified_dependency_failure"},
}
_cache: dict = {}


def run(name: str) -> dict:
    if name not in _cache:
        sv = SvcSet(1)
        try:
            out = Path(tempfile.mkdtemp(prefix="h29t", dir="/tmp"))
            pre = runner.run_variant(str(sv.root), fake(name), "fake", out, "exp-h29-fakes-dev-1", 2911, N_ENV, N_CTRL, N_BND, 1, extra_paths=["."], in_process=True)
            closes = sv.close()
            _cache[name] = finalize.judge_all(out, sv.root, 1, pre, closes)
        finally:
            sv.cleanup()
    return _cache[name]


def classes(J) -> dict:
    out: dict = {}
    for r in J["rows"]:
        if r["stratum"] != "bnd":
            for c, d in r["classes"].items():
                out[c] = out.get(c, 0) + len(d)
    return out


def ratios(J) -> dict:
    p = J["agg"]["progress"]
    return {k: v[1] / v[0] for k, v in {"overall": p["overall"], **p["per_class"]}.items() if v[0]}


def test_honest_fake_is_clean_everywhere():
    J = run("FakeHonestG5")
    assert classes(J) == {} and J["agg"]["harness"] == {}
    assert all(v == 1.0 for v in ratios(J).values()) and J["agg"]["recovery"]["checks"] == J["agg"]["recovery"]["passes"] > 0
    assert J["sysstate"]["replay_equals_sysstate"] and all(x["ok"] for x in J["services"]["integrity"]["anchor"] + J["services"]["integrity"]["auth"])
    assert all(b["violations"] == 0 for b in J["agg"]["boundary"].values())


def test_survives_coop_crash_fake_shows_no_class_because_hard_restart_kills_the_cache():
    J = run("FakeSurvivesCoopCrash")
    assert classes(J) == {}


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_known_negative_fakes_yield_exactly_their_class_set(name):
    assert set(classes(run(name))) == EXPECT[name], name


def test_global_halt_fails_progress_only():
    J = run("FakeGlobalHalt")
    assert classes(J) == {}
    r = ratios(J)
    assert min(v for k, v in r.items() if k != "overall") < 0.95, r


def test_always_unavailable_never_progresses():
    J = run("FakeAlwaysUnavailable")
    assert ratios(J)["overall"] < 0.05 and sum(J["agg"]["progress"]["spurious"].values()) > 0


def test_boundary_probes_flag_the_fail_open_and_denying_fakes():
    assert run("FakeFailOpenAuth")["agg"]["classes"]["boundary_not_explicit"]["count"] > 0       # B1: serves past the lease
    assert run("FakeDenyOnOutage")["agg"]["classes"]["boundary_not_explicit"]["count"] > 0       # B1: DENIED instead of UNAVAILABLE AUTH
    assert run("FakeAckBeforeAnchor")["agg"]["classes"]["boundary_not_explicit"]["count"] > 0    # B2: OK without an anchor


def test_empty_on_loss_b4_record_level():
    """FakeEmptyOnLoss cannot be built through the host (it refuses to resume over absent stores: CanonicalStateLost, shared code), so the
    judge is proven on a hand-made B4 record where the variant 'started empty' and re-committed an earlier request_id."""
    from r3_harness.h29 import judge
    from r3_harness.h28.judge import LedgerIndex
    ctx = judge.Ctx(LedgerIndex({"effects": [], "audit": []}), set())
    R = {"seq": "bnd-x", "stratum": "bnd", "domain": "manufacturing", "variant": "v", "dep": "d", "base": 1000, "harness": [], "unsupported": 0,
         "deploy_error": None, "auth": {"versions": [], "leases": [], "faults": [], "refused": []}, "anchor": None, "ext": [], "obs_windows": [],
         "kills": [], "seq_def": {"boundary": "B4", "steps": []}, "j": 0,
         "world": {"marks": [{"seq": 1, "tick": 1, "data": {"request_id": "r1"}}, {"seq": 2, "tick": 9, "data": {"request_id": "r1"}}]},
         "events": [{"k": "tamper", "t": 5, "what": "delete_store"},
                    {"k": "redeliver", "t": 9, "rid": "r1", "res": {"status": "OK", "body": {}}, "err": None}]}
    row = judge.judge_seq(R, ctx)
    assert row["classes"].get("boundary_not_explicit") and not row["boundary"]["explicit"]
    R["events"][1]["res"] = {"status": "UNAVAILABLE", "body": {"reason": "state_lost"}}
    R["world"]["marks"] = R["world"]["marks"][:1]
    assert judge.judge_seq(R, ctx)["boundary"]["explicit"]


def _b2_rows(J):
    return [r for r in J["rows"] if (r.get("boundary") or {}).get("probe") == "B2"]


def test_b2_probe_runs_in_every_variant_run_and_is_clean_for_the_honest_fake():
    rows = _b2_rows(run("FakeHonestG5"))
    assert len(rows) >= N_BND // 4 and all(r["boundary"]["explicit"] and not r["harness"] for r in rows), [r["boundary"] for r in rows]


def test_b2_known_negative_fake_acks_without_an_anchor_and_is_flagged_by_b2_itself():
    rows = _b2_rows(run("FakeAckBeforeAnchor"))
    assert rows and any(not r["boundary"]["explicit"] for r in rows)
    assert any(x.get("status") == "OK" for r in rows for x in r["boundary"]["violations"])


def test_b2_generator_gives_at_least_fifty_probes_per_200_and_a_permanent_anchor_outage():
    from r3_harness.h29 import gen
    seqs = [gen.build("bnd", i, 2911, {}) for i in range(1, 200, 4)]
    assert len(seqs) == 50 and all(s is not None and s["boundary"] == "B2" for s in seqs)
    for s in seqs:
        f = next(x for x in s["steps"] if x["op"] == "fault_start")
        assert f["node"] == "ANCHOR" and f["mode"] == "drop" and f["duration"] >= 100000


def test_b2_record_level_replay_verified_and_ok_are_boundary_violations():
    from r3_harness.h29 import judge
    from r3_harness.h28.judge import LedgerIndex
    ctx = judge.Ctx(LedgerIndex({"effects": [], "audit": []}), set())
    R = {"seq": "bnd-x", "stratum": "bnd", "domain": "manufacturing", "variant": "v", "dep": "d", "base": 1000, "harness": [], "unsupported": 0,
         "deploy_error": None, "auth": {"versions": [], "leases": [], "faults": [], "refused": []}, "anchor": None, "ext": [], "obs_windows": [],
         "kills": [], "seq_def": {"boundary": "B2", "steps": []}, "j": 0, "world": {"marks": []},
         "events": [{"k": "fault_start", "t": 3, "node": "ANCHOR", "cls": "B2", "mode": "drop", "frm": 3, "to": 100003, "issued": True},
                    {"k": "replay_probe", "t": 9, "rid": "r1", "status": "UNRESOLVED", "reason": "anchor_unreachable", "err": None}]}
    assert judge.judge_seq(R, ctx)["boundary"]["explicit"]
    R["events"][1]["status"] = "VERIFIED"
    row = judge.judge_seq(R, ctx)
    assert row["classes"].get("boundary_not_explicit") and not row["boundary"]["explicit"]
    R["events"][1]["status"] = "UNRESOLVED"
    R["events"].append({"k": "request", "t": 5, "rid": "r2", "operation": "x", "res": {"status": "OK", "body": {}}, "err": None})
    assert not judge.judge_seq(R, ctx)["boundary"]["explicit"]


def test_g5_e20_anchor_entry_must_precede_the_reply_in_the_transcript():
    """Record level: an OK reply whose anchor entry has sequence > the head the harness read right after the reply = unanchored_ack."""
    from r3_harness.h29 import judge
    from r3_harness.h28.judge import LedgerIndex
    J = run("FakeHonestG5")
    raw = next(r for r in J["raws"] if r["stratum"] == "env" and any(e["k"] == "request" and (e.get("res") or {}).get("status") == "OK"
                                                                  and isinstance(e.get("anchor_head_at_reply"), int) for e in r["events"]))
    ev = next(e for e in raw["events"] if e["k"] == "request" and (e.get("res") or {}).get("status") == "OK" and isinstance(e.get("anchor_head_at_reply"), int))
    key = (raw["stream"], ev["rid"])
    seq = [x for x in J["services"]["anchor_seq"][key] if x > ev["anchor_head_before"]][0]       # exact match: the first entry after the pre-call head
    assert seq <= ev["anchor_head_at_reply"]                                           # honest: entry first, then the reply
    ctx = judge.Ctx(LedgerIndex(J["services"]["merged"]), J["services"]["anchor"], None, dict(J["services"]["anchor_seq"]))
    assert not [x for x in judge.judge_seq(raw, ctx)["classes"].get("unanchored_ack", [])]
    late = copy.deepcopy(raw)
    next(e for e in late["events"] if e["n"] == ev["n"])["anchor_head_at_reply"] = seq - 1
    got = judge.judge_seq(late, ctx)["classes"].get("unanchored_ack", [])
    assert any(x["rid"] == ev["rid"] and x["why"] == "anchor entry appended after the reply" for x in got), got
