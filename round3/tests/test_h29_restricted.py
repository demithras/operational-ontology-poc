"""G5-E25 (restricted-phase I/O is a recovery_divergence, window bounded by TRANSCRIPT ORDER) and G5-E26 (outcome-plane known-negative).
G5-E27 note: the oracle form comparison / audit placement corrections of fix1 are tested in test_h29_oracle.py (world_digest by form) and
test_h29_machine.py; this file only adds the E25/E26 cases. Record-level cases are built from a real FakeHonestG5 run."""
import copy
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from r3_harness.h28.judge import LedgerIndex
from r3_harness.h29 import aggregate, evaluator, judge, judge_fin, rc
from tests.test_h29_fakes import classes, run

ROOT = Path(__file__).resolve().parents[1]


def _ctx(J):
    sv = J["services"]
    return judge.Ctx(LedgerIndex(sv["merged"]), sv["anchor"], None, dict(sv["anchor_seq"]))


def _rc1_raw(J):
    return next(r for r in J["raws"] if r["stratum"] == "env" and any(e["k"] == "rc1" for e in r["events"]))


def _restricted(row):
    return [d for d in row["classes"].get("recovery_divergence", []) if d.get("what") == "restricted_io"]


def test_g5_e25_honest_record_has_no_restricted_io():
    J = run("FakeHonestG5")
    assert all(not r["restricted_io"] and not _restricted(r) for r in J["rows"])
    assert J["agg"]["recovery"]["restricted_io"] == 0 and J["agg"]["classes"]["recovery_divergence"]["count"] == 0


def test_g5_e25_fetch_inside_the_window_is_a_recovery_divergence():
    J = run("FakeHonestG5")
    raw = copy.deepcopy(_rc1_raw(J))
    e = next(x for x in raw["events"] if x["k"] == "rc1")
    e["auth_refused_restricted"] = 2                                   # recorded between the pre/post RC1 service sequence marks
    row = judge.judge_seq(raw, _ctx(J))
    assert row["restricted_io"] and _restricted(row) and row["restricted_io"][0]["n"] == 2
    assert "AuthorityService" in _restricted(row)[0]["detail"]


def test_g5_e25_fetch_after_the_first_api_call_at_the_same_tick_is_not_counted():
    """A refusal row stamped with the resume tick but sequenced AFTER the window (auth_refused_restricted == 0) is not restricted_io."""
    J = run("FakeHonestG5")
    raw = copy.deepcopy(_rc1_raw(J))
    e = next(x for x in raw["events"] if x["k"] == "rc1")
    raw["auth"]["refused"].append({"tick": e["resume"], "deployment": raw["dep"], "op": "fetch", "reason": "outage"})
    e["auth_refused_restricted"] = 0
    row = judge.judge_seq(raw, _ctx(J))
    assert row["restricted_io"] == [] and not _restricted(row)


def test_g5_e25_window_is_bounded_by_service_sequence_not_tick():
    rows = [{"seq": s, "deployment": "d", "tick": 7} for s in (3, 4, 5, 6)]
    r = SimpleNamespace(dep="d", svc=SimpleNamespace(auth=SimpleNamespace(log=lambda: {"refused": rows})))
    assert rc._auth_seq(r) == 6
    assert rc._auth_refused_between(r, 3, 5) == 2 and rc._auth_refused_between(r, 6, 6) == 0 and rc._auth_refused_between(r, None, 6) == 0


def test_g5_e25_anchor_append_during_rc1_rejects_the_variant():
    """The class reaches the VERDICT, not just the row: head moved across RC1 -> restricted_io -> recovery_divergence -> REJECTED."""
    J = run("FakeHonestG5")
    raws = copy.deepcopy(J["raws"])
    raw = next(r for r in raws if r["stratum"] == "env" and any(e["k"] == "rc1" for e in r["events"]))
    e = next(x for x in raw["events"] if x["k"] == "rc1")
    e["anchor_head_before"], e["anchor_head_after"] = 3, 4
    ctx = _ctx(J)
    rows = [judge.judge_seq(R, ctx) for R in raws]
    assert any(_restricted(r) for r in rows)
    agg = aggregate.aggregate(rows)
    assert agg["classes"]["recovery_divergence"]["count"] > 0
    t = json.loads((ROOT / "protocol/thresholds.json").read_text())["H29"]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "mutants.json").write_text("{}")
        from r3_harness.h29 import evidence_out
        (Path(d) / evidence_out.FILES[5]).write_text("{}")
        bad = evaluator._verdict(Path(d), "v", t, True, {}, agg, J, True, [], {})
        ok = evaluator._verdict(Path(d), "v", t, True, {}, J["agg"], J, True, [], {})
    assert bad["verdict"] == "REJECTED" and "recovery_divergence" in str(bad["metrics"]["classes"]), bad["reasons"]
    assert ok["verdict"] != "REJECTED", ok["reasons"]


def _outcome_plane(row):
    return row["mis"].get("outcome-plane", [])


def test_g5_e26_outcome_plane_reconciled_failed_under_fault_is_misclassified(monkeypatch):
    """RECONCILED_FAILED while the oracle state is PENDING/UNKNOWN under an EXT/OBS fault -> misclassified_dependency_failure; the identical
    report without the fault is not (G5-E26). Non-vacuity: this test goes red when the judge's outcome-plane branch is disabled."""
    J = run("FakeHonestG5")
    ctx = _ctx(J)
    found = None
    for raw in J["raws"]:
        if raw["stratum"] != "env":
            continue
        for ev in (x for x in raw["events"] if x["k"] == "reconcile" and (x.get("res") or {}).get("status") == "OK" and x.get("fault")):
            outs = (ev["res"].get("body") or {}).get("outcomes") or []
            if not outs or outs[0].get("state") not in ("PENDING", "UNKNOWN"):
                continue
            bad = copy.deepcopy(raw)
            b = next(x for x in bad["events"] if x["n"] == ev["n"])
            b["res"]["body"]["outcomes"][0]["state"] = "RECONCILED_FAILED"
            faulted = judge.judge_seq(bad, ctx)                         # the recorded EXT/OBS fault is in force
            b["fault"] = None                                           # the identical report with no fault on the read ...
            monkeypatch.setattr(judge_fin, "_fault_at", lambda phi: (lambda s, a, c: False))        # ... and none in the window
            clean = judge.judge_seq(bad, ctx)
            monkeypatch.undo()
            if _outcome_plane(faulted) and not _outcome_plane(clean):
                found = (faulted, clean)
                break
        if found:
            break
    assert found, "no faulted honest reconcile read with an oracle PENDING/UNKNOWN state exists in the dev run"
    faulted, clean = found
    assert faulted["classes"].get("misclassified_dependency_failure")
    assert not _outcome_plane(clean)


def test_g5_e27_world_digest_compares_loose_verdict_props_by_form():
    from r3_oracle import recoverymodel as RM
    mk = lambda reason, h: {"objects": {"Verdict:v1": {"props": {"reason": reason, "derivation_hash": h, "state": "ok"}}}, "links": []}  # noqa: E731
    a, b = mk("granted by rule A", "a" * 64), mk("allowed (rule B text)", "b" * 64)
    assert RM.world_digest(a) == RM.world_digest(b)                                   # same form: non-blank / 64 hex
    assert RM.world_digest(a) != RM.world_digest(mk("", "a" * 64)) and RM.world_digest(a) != RM.world_digest(mk("x", "zz"))
    c = mk("x", "a" * 64)
    c["objects"]["Verdict:v1"]["props"]["state"] = "denied"                           # a strict prop still differs
    assert RM.world_digest(a) != RM.world_digest(c)


def test_g5_e27_unverified_ledger_rows_are_placed_by_the_claimed_deployment():
    class Led:
        ledger = {"unverified": [{"claim": {"deployment": "d1", "system": "WMS"}, "tick": 1010, "outcome": "refused", "reason": "unavailable"},
                                 {"claim": {"deployment": "other", "system": "WMS"}, "tick": 1011, "outcome": "refused", "reason": "unavailable"}]}
        dep_ledger = staticmethod(lambda dep: {"effects": [], "audit": []})
    from r3_harness.h29 import judge_ext
    dl = judge_ext.dep_ledger(Led(), "d1", 1000)
    assert [r["tick"] for r in dl["unverified"]] == [10]                              # by claim, relative frame; attribution evidence stays absent


# ---- G5-E25 completeness: ExternalWorld request / observer read inside the restricted window ---------------------------------------------
def _with_rc1(J, **kw):
    raw = copy.deepcopy(_rc1_raw(J))
    e = next(x for x in raw["events"] if x["k"] == "rc1")
    e.update(kw)
    return judge.judge_seq(raw, _ctx(J))


def test_g5_e25_ext_request_inside_the_window_is_a_recovery_divergence():
    J = run("FakeHonestG5")
    row = _with_rc1(J, ext_restricted=3)
    assert any("ExternalWorld" in d["detail"] and d["n"] == 3 for d in _restricted(row))


def test_g5_e25_ext_request_after_the_first_api_call_is_not_counted():
    """rc.py bounds the window by the ExternalWorld audit seq at the two RC1 marks: rows sequenced after the second mark are outside it."""
    import sqlite3
    d = Path(tempfile.mkdtemp(prefix="h29x", dir="/tmp"))
    con = sqlite3.connect(d / "external.db")
    con.executescript("CREATE TABLE audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, deployment TEXT, tick INT);"
                      "CREATE TABLE unverified_claim(audit_seq INTEGER PRIMARY KEY, claim_json TEXT);"
                      "INSERT INTO audit(deployment,tick) VALUES('d',1),('d',7),('',7),('other',7),('d',7);"
                      "INSERT INTO unverified_claim VALUES(3,'{\"deployment\":\"d~rc1b\"}');")
    con.commit()
    con.close()
    r = SimpleNamespace(dep="d", svc=SimpleNamespace(ext_dir=str(d)))
    assert rc._ext_seq(r) == 5
    assert rc._ext_between(r, 1, 4) == 2            # seq 2 (attributed) + seq 3 (unverified, claimed d~rc1b); seq 4 is another deployment
    assert rc._ext_between(r, 4, 4) == 0 and rc._ext_between(r, 4, 5) == 1 and rc._ext_between(r, None, 5) == 0
    assert rc._ext_between(SimpleNamespace(dep="d", svc=SimpleNamespace(ext_dir=str(d / "none"))), 0, 5) == 0


def test_g5_e25_observer_read_inside_the_window_and_missing_log_is_invalid():
    J = run("FakeHonestG5")
    assert any("observer" in d["detail"] for d in _restricted(_with_rc1(J, obs_reads_restricted=2)))
    assert _with_rc1(J, obs_reads_restricted=0)["restricted_io"] == []             # after the first API call at the same tick: nothing
    row = _with_rc1(J, obs_reads_restricted=None)
    assert not _restricted(row) and row["obs_reads_instrumented"] is False
    assert "observer_log_missing" in row["harness"]                                # a G5 run without the read log is a harness INVALID, not clean
    assert all(r["obs_reads_instrumented"] and "observer_log_missing" not in r["harness"] for r in J["rows"] if r["stratum"] == "env")


def _rc1_row(J):
    return next(r for r in J["rows"] if any(e["k"] == "rc1" for e in next(x for x in J["raws"] if x["seq"] == r["seq"])["events"]))


def test_g5_e25_honest_fake_clean_and_dispatching_fake_rejected():
    assert all(not r["restricted_io"] for r in run("FakeHonestG5")["rows"])
    J = run("FakeDispatchInRC1")
    assert any(any("ExternalWorld" in d["detail"] for d in _restricted(r)) for r in J["rows"]), "no ExternalWorld request seen inside RC1"
    assert "recovery_divergence" in classes(J)
    t = json.loads((ROOT / "protocol/thresholds.json").read_text())["H29"]
    with tempfile.TemporaryDirectory() as d:                       # the class reaches the VERDICT
        (Path(d) / "mutants.json").write_text("{}")
        from r3_harness.h29 import evidence_out
        (Path(d) / evidence_out.FILES[5]).write_text("{}")
        v = evaluator._verdict(Path(d), "v", t, True, {}, J["agg"], J, True, [], {})
    assert v["verdict"] == "REJECTED" and "recovery_divergence" in str(v["metrics"]["classes"]), v["reasons"]


def test_anchor_seq_lists_every_entry_of_a_reused_request_id():
    from r3_harness.h29 import finalize
    a: dict = {}
    for seq in (7, 3):
        finalize.note_anchor_seq(a, {"stream": "s", "decision_id": "r004", "seq": seq})
    assert a == {("s", "r004"): [3, 7]}


def test_anchor_entry_exact_match_cases():
    """G5-E20 exact match (record level). seqs = entries with decision_id == request_id; before/after = heads read around the call."""
    from r3_harness.h29.judge_req import _anchor_entry_violation as V
    assert V([3], 2, 3, True) is None                                      # honest: entry in (before, after]
    assert V([3], 2, 2, True)["why"] == "anchor entry appended after the reply"      # OK whose entry lands after the reply
    assert V([3, 7], 2, 3, True) is None                                   # deny-then-succeed order irrelevant: first NEW entry is the success
    assert V([3, 7], 6, 7, True) is None and V([3, 7], 6, 6, True)["entry_seq"] == 7  # success (7) after an earlier deny (3): judges seq 7, not 3
    assert "earlier entry" in V([3], 5, 9, True)["why"]                    # fresh OK, only an old entry of a reused id: missing entry for THIS decision
    assert V([3], 5, 9, False) is None                                     # idempotent replay may rest on the earlier entry
    assert V([], 5, 9, True)["why"] == "no anchor entry"
    assert V([3], None, 3, True) is None and V([3], 2, -1, True)["harness"] == "anchor_head_unreadable"   # G5-E31: unreadable head after OK is a harness row


def test_g5_e25_observer_reading_fake_is_rejected():
    J = run("FakeObserveInRC1")
    assert any(any("observer" in d["detail"] for d in _restricted(r)) for r in J["rows"]), "no observer read seen inside RC1"
    t = json.loads((ROOT / "protocol/thresholds.json").read_text())["H29"]
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "mutants.json").write_text("{}")
        from r3_harness.h29 import evidence_out
        (Path(d) / evidence_out.FILES[5]).write_text("{}")
        v = evaluator._verdict(Path(d), "v", t, True, {}, J["agg"], J, True, [], {})
    assert v["verdict"] == "REJECTED" and "recovery_divergence" in str(v["metrics"]["classes"]), v["reasons"]
