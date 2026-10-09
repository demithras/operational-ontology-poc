"""Gate 4 fix round 1 (errata G4-E21..E24): transcript mismatch -> INVALID, GEN-NULL op `record`, measured envelope check, oracle clamp."""
import json
from pathlib import Path

from r3_harness.h28 import evaluator, finalize, judge, specs
from r3_oracle import extoracle
from tests.test_h28_e2e import R3, exp  # noqa: F401  (module fixture)


def test_gen_null_operation_is_named_record():
    assert specs.GEN_OP == "record"
    ops, auth, _ = specs.load("manufacturing")
    ops2, auth2 = specs.with_gen_null(ops, auth)
    assert [o["name"] for o in ops2["operations"]].count("record") == 1
    assert not any("record_generated" in json.dumps(x) for x in (ops2, auth2))


def test_oracle_observer_view_clamps_to_server_tick():
    ledger = {"effects": [], "audit": []}
    systems = specs.combined_systems()
    assert extoracle.observer_view(ledger, "d", systems, 50, 0, 7)["complete_through_tick"] == 7
    assert extoracle.observer_view(ledger, "d", systems, 50, 2, 7)["complete_through_tick"] == 7
    assert extoracle.observer_view(ledger, "d", systems, 5, 2, 7)["complete_through_tick"] == 3
    assert extoracle.observer_view(ledger, "d", systems, 5, 0)["complete_through_tick"] == 5      # no server tick given: unclamped


def _rec(env_text, **kw):
    return {"recorder": {"ERP": [{"request_id": "r1", "effect_index": 0, "envelope_text": env_text}]},
            "auditor_env": {"r1": {"v": 1, "decision": {"decision_id": "r1"}}}, **kw}


def test_envelope_check_is_measured_and_crash_cases_excluded():
    good = json.dumps({"decision": {"decision_id": "r1"}, "v": 1})
    assert judge.envelope_mismatches(_rec(good)) == []
    for bad in ("", "not json", json.dumps({"v": 1, "decision": {"decision_id": "r2"}})):
        assert len(judge.envelope_mismatches(_rec(bad))) == 1                          # known negatives
    assert judge.envelope_mismatches(_rec("", crash=True)) == []                       # G4-E18
    none_aud = {**_rec(good), "auditor_env": {"r1": None}}
    assert judge.envelope_mismatches(none_aud) == []                                   # no anchor: not measurable
    assert len(judge.envelope_mismatches({**none_aud, "anchor": True})) == 1           # anchor: auditor envelope required


def test_honest_run_actually_measures_envelopes(exp):  # noqa: F811
    d = exp[0] / "exp-h28-e2e-dev-1" / "fake-FakeHonest"
    seen = 0
    for line in (d / "cases.jsonl").read_text().splitlines():
        R = json.loads(line)
        if R.get("auditor_env") and R.get("recorder") and not R.get("crash"):
            seen += sum(1 for log in R["recorder"].values() for e in log if e["request_id"] in R["auditor_env"])
    assert seen > 0, "envelope check ran over zero recorder entries (vacuous)"


def test_transcript_mismatch_makes_the_run_invalid(exp, monkeypatch):  # noqa: F811
    vdir = exp[0] / "exp-h28-e2e-dev-1" / "fake-FakeHonest"
    th = json.loads((R3 / "protocol" / "thresholds.json").read_text())
    base = evaluator.evaluate_variant(vdir, th, "fake-FakeHonest", True)
    assert base["verdict"] == "SUPPORTED", base["reasons"]
    real = finalize.aggregate

    def tampered(J):
        agg = real(J)
        agg["harness"] = {**agg["harness"], "ext_transcript_mismatch": 3}
        return agg

    monkeypatch.setattr(finalize, "aggregate", tampered)
    v = evaluator.evaluate_variant(vdir, th, "fake-FakeHonest", True)
    assert v["verdict"] == "INVALID" and any("ext_transcript_mismatch" in r for r in v["reasons"])
