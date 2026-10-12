"""Known-negative fakes of ORACLE-AND-HARNESS-G5 s10 (never registered): each yields its expected class set on S-env/S-ctrl rows, the
honest oracle-backed fake yields none. Superset tolerance is explicit per fake: R29-7 read literally makes any OK/DENIED answer to a
BLOCKED request a misclassification, which s10's one-line expectations omit (reported to the orchestrator as a frozen-text gap)."""
import json
import tempfile
from pathlib import Path

import pytest

from r3_harness.h29 import finalize, runner
from r3_harness.h29.svcset import SvcSet
from tests.fakes.h29_rig import fake

N_ENV, N_CTRL, N_BND = 48, 4, 8
MIS = {"misclassified_dependency_failure"}
EXPECT = {   # fake -> (core classes that MUST appear, extra classes tolerated)
    "FakeFailOpenAuth": ({"stale_authority_commit", "forbidden_effect"}, MIS | {"disclosure_leak", "recovery_divergence"}),
    "FakeStaleRestart": ({"stale_authority_after_restart"}, MIS | {"stale_authority_commit", "forbidden_effect", "disclosure_leak", "recovery_divergence"}),
    "FakeRandomRecovery": ({"recovery_nondeterministic"}, set()),
    "FakeDenyOnOutage": ({"misclassified_dependency_failure"}, set()),
    "FakeDropOutbox": ({"recovery_divergence"}, MIS),
    "FakeAckBeforeAnchor": ({"unanchored_ack"}, MIS),
    "FakeMisattributes": ({"misclassified_dependency_failure"}, set()),
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
def test_known_negative_fakes(name):
    core, extra = EXPECT[name]
    got = set(classes(run(name)))
    assert core <= got, (name, got)
    assert got <= core | extra, (name, got - core - extra)


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
