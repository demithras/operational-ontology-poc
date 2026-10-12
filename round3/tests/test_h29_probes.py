"""G5-E28: input-invalid probes (a), strict judge predicate + admissible replies (b), two lease windows (c). Record-level cases come from a real
FakeHonestG5 run; every new check has a known-negative that goes red."""
import copy

from r3_harness.h29 import gen, judge, rules
from r3_harness.h29.judge_req import envelope_invalid
from r3_oracle import continuity as C
from r3_oracle import ops_model
from tests.test_h29_fakes import run
from tests.test_h29_restricted import _ctx


def _probe_events(J):
    return [(raw, e) for raw in J["raws"] if raw["stratum"] == "env" for e in raw["events"] if e["k"] == "request" and e.get("invalid_probe")]


# ---- (a) corpus ---------------------------------------------------------------------------------------------------------
def test_g5_e28a_generator_emits_every_shape_marked_and_schema_invalid():
    stats, shapes, n = {}, {}, 0
    for i in range(120):
        s = gen.build("env", i, 2911, stats)
        ops = None
        for st in s["steps"]:
            rules.validate_step(st)
            if st["op"] == "request" and st.get("invalid_probe"):
                n += 1
                shapes[st["probe_shape"]] = shapes.get(st["probe_shape"], 0) + 1
                assert st["probe_shape"] in rules.PROBE_SHAPES
                if st["probe_shape"] == "unknown_operation":
                    assert st["operation"] == rules.PROBE_UNKNOWN_OP and st["surface"] == "direct"
                elif st["probe_shape"] == "unknown_tool":
                    assert st["operation"] == rules.PROBE_UNKNOWN_TOOL and st["surface"] == "call_tool"
                else:
                    from r3_harness.h29 import specs
                    spec = ops_model.op_of(specs.load(s["domain"])[0], st["operation"])
                    assert spec is not None and not ops_model.schema_valid_args(spec, st["args"]), st
            elif st["op"] == "request":
                assert "probe_shape" not in st
    assert set(shapes) == set(rules.PROBE_SHAPES) and n >= 100, (shapes, n)


def test_g5_e28a_probes_reach_the_transcript_in_healthy_phases_and_in_auth_anchor_windows():
    J = run("FakeHonestG5")
    ev = _probe_events(J)
    assert ev and all(e.get("probe_shape") in rules.PROBE_SHAPES for _, e in ev)
    recs = [q for r in J["rows"] for q in r["req"] if q.get("probe")]
    assert any(not q["phi"] for q in recs) and any(set(q["phi"]) & {"AUTH", "ANCHOR"} for q in recs)
    p = J["agg"]["probes"]
    nb = sum(len((r.get("boundary") or {}).get("probes", [])) for r in J["rows"])
    assert p["total"] == len(recs) + nb and p["in_auth_anchor_window"] > 0 and set(p["per_shape"]) == set(rules.PROBE_SHAPES), p
    assert all(q["input_invalid"] for q in recs) and not any(q["input_invalid"] for r in J["rows"] for q in r["req"] if not q.get("probe") and q.get("k") == "request" and q["rid"] and q["oracle"] == "OK")


def test_g5_e28a_judge_fin_and_judge_read_invalid_probe_from_the_same_event_key():
    import inspect
    from r3_harness.h29 import judge_fin
    assert 'e.get("invalid_probe")' in inspect.getsource(judge_fin._boundary) and "False}" not in inspect.getsource(judge_fin._boundary).split("sends = ")[1].split("renew")[0]


def test_g5_e28a_floor_makes_the_verdict_inconclusive():
    import json
    import tempfile
    from pathlib import Path
    from r3_harness.h29 import evaluator, evidence_out
    from tests.test_h29_restricted import ROOT
    J = run("FakeHonestG5")
    t = json.loads((ROOT / "protocol/thresholds.json").read_text())["H29"]
    agg = copy.deepcopy(J["agg"])
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / evidence_out.FILES[5]).write_text("{}")
        ov = {"min_probe_window": agg["probes"]["in_auth_anchor_window"]}
        ok = evaluator._verdict(Path(d), "v", t, True, ov, agg, J, True, [], {})
        agg["probes"]["in_auth_anchor_window"] -= 1
        bad = evaluator._verdict(Path(d), "v", t, True, ov, agg, J, True, [], {})
    assert not any("G5-E28" in r for r in ok["reasons"]) and any("G5-E28" in r for r in bad["reasons"]) and bad["verdict"] != "SUPPORTED"


# ---- (b) predicate and admissible replies -------------------------------------------------------------------------------
def test_g5_e28b_envelope_and_strict_schema_are_the_input_invalid_predicate():
    assert envelope_invalid("", None) and envelope_invalid(None, None) and envelope_invalid("r1", 5) and not envelope_invalid("r1", None)
    assert not envelope_invalid("r1", "someone")


def _blocked_probe(J):
    for raw, e in _probe_events(J):
        if e.get("res") and e["res"]["status"] in ("UNAVAILABLE", "INVALID", "UNKNOWN"):
            row = next(r for r in J["rows"] if r["seq"] == raw["seq"])
            q = next((q for q in row["req"] if q["n"] == e["n"]), None)
            if q and q["cls"] == "BLOCKED_BY_DEPENDENCY" and q["down"]:
                return raw, e, q
    return None


def test_g5_e28b_admissible_replies_for_an_input_invalid_request_while_blocked():
    J = run("FakeHonestG5")
    found = _blocked_probe(J)
    assert found, "no probe was BLOCKED in the dev run"
    raw, e, q = found
    ctx = _ctx(J)

    def verdict(status, body):
        r = copy.deepcopy(raw)
        ev = next(x for x in r["events"] if x["n"] == e["n"])
        ev["res"] = {"status": status, "body": body}
        return [m for m in judge.judge_seq(r, ctx)["mis"].get("INVALID", []) + judge.judge_seq(r, ctx)["mis"].get(status, []) if m.get("rid") == e["rid"]]
    for reason in ("schema_invalid", "unknown_operation", "unknown_tool", "bad_args"):         # any member of INPUT_INVALID_REASONS
        assert not verdict("INVALID", {"reason": reason}), reason
    assert not verdict("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": q["down"][0]})
    # known negatives
    assert verdict("INVALID", {"reason": "zz_unmapped_free_text"})
    assert verdict("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "EXT:NOTIFY"})
    assert verdict("DENIED", {"reason": "no allow grant"})
    assert verdict("OK", {})


def test_g5_e28b_invalid_reply_to_an_input_valid_request_while_blocked_stays_a_misclassification():
    c = C.Cls(C.BLOCKED, ["AUTH"])
    assert C.blocked_reply_ok(c, "INVALID", {"reason": "schema_invalid"}, True)[0]
    assert not C.blocked_reply_ok(c, "INVALID", {"reason": "schema_invalid"}, False)[0]


# ---- (c) two lease windows --------------------------------------------------------------------------------------------------
GRAPH = None


def _setup():
    from r3_harness.h29 import specs
    g = specs.graph()
    phi = C.Phi([{"node": "AUTH", "mode": "drop", "from_tick": 5, "to_tick": 30}], [])
    sends = [{"kind": "request", "op": "reschedule_work_order", "t": 1, "invalid_probe": False},
             {"kind": "request", "op": "reschedule_work_order", "t": 4, "invalid_probe": True}]
    ver = [{"effective_tick": 0, "seq": 1, "digest": "d", "doc": {}, "requested_tick": 0}]
    return g, phi, sends, ver


def test_g5_e28c_obligation_window_ignores_probes_admissibility_window_counts_them():
    g, phi, sends, ver = _setup()
    r = C.renew_pair(sends, phi, g, "manufacturing")
    assert list(r) == [1] and r.adm == [1, 4]
    q = lambda t: {"kind": "request", "op": "reschedule_work_order", "t": t, "rid": "x"}      # noqa: E731
    assert C.classify(q(4), phi, g, "manufacturing", r, ver).kind == C.SAFE                      # AUTH up at 4
    assert C.classify(q(5), phi, g, "manufacturing", r, ver).gap                                  # lease from tick 1 ended at 5; the probe's runs to 8
    gap = C.classify(q(6), phi, g, "manufacturing", r, ver)
    assert gap.kind == C.SAFE and gap.gap and not gap.strict                                   # in the probe-granted window only
    assert C.classify(q(8), phi, g, "manufacturing", r, ver).kind == C.BLOCKED                  # past both windows
    plain = C.Renew(r)                                                                          # known negative: no admissibility window -> BLOCKED
    assert C.classify(q(6), phi, g, "manufacturing", plain, ver).kind == C.BLOCKED
    inside = C.classify(q(3), C.Phi([{"node": "AUTH", "mode": "drop", "from_tick": 2, "to_tick": 30}], []), g, "manufacturing", r, ver)
    assert inside.kind == C.SAFE and inside.strict and not inside.gap                          # obligation window: unchanged behaviour


def _gap_record(J):
    """An honest raw with a probe sent while AUTH is up and a later request that the probe's lease (but not a normal one) covers."""
    for raw in J["raws"]:
        if raw["stratum"] != "env" or raw.get("kills"):
            continue
        row = next(r for r in J["rows"] if r["seq"] == raw["seq"])
        for q in row["req"]:
            if q["cls"] != C.BLOCKED or q["down"] != ["AUTH"] or q["k"] != "request" or not q.get("rid"):
                continue
            ev = next(x for x in raw["events"] if x["n"] == q["n"])
            starts = [w for w in raw["faults"].values() if w["node"] == "AUTH"]
            if not starts:
                continue
            f = min(w["from"] for w in starts)
            tp = q["t"] - 2
            if tp < 1 or tp >= f or raw["events"][0]["t"] > tp:
                continue
            return raw, ev, tp
    return None


def test_g5_e28c_request_in_the_gap_may_be_decided_or_unavailable_and_is_counted_not_owed():
    J = run("FakeHonestG5")
    found = _gap_record(J)
    assert found, "no AUTH-blocked request with room for a preceding probe in the dev run"
    raw, ev, tp = found
    ctx = _ctx(J)
    r = copy.deepcopy(raw)
    base_ev = next(x for x in r["events"] if x["k"] == "request" and x.get("res"))
    probe = {**copy.deepcopy(base_ev), "rid": "pgap", "t": tp, "invalid_probe": True, "probe_shape": "unknown_key", "tag": "probe",
             "args": {**base_ev["args"], "zz_unknown_key": 1}, "res": {"status": "INVALID", "body": {"reason": "schema_invalid"}}, "n": 9999}
    i = next(k for k, x in enumerate(r["events"]) if x["t"] > tp)
    r["events"].insert(i, probe)
    tgt = next(x for x in r["events"] if x["n"] == ev["n"])
    plain = judge.judge_seq(copy.deepcopy(raw), ctx)
    for res in ({"status": "UNAVAILABLE", "body": {"reason": "dependency_unavailable", "dependency": "AUTH"}}, {"status": "DENIED", "body": {"reason": "x"}}):
        tgt["res"] = res
        row = judge.judge_seq(r, ctx)
        q = next(q for q in row["req"] if q["n"] == ev["n"])
        assert q["lease_gap"] and q["cls"] == C.SAFE and not q["eligible"] and q["spurious"] is None, q
        assert not [m for v in row["mis"].values() for m in v if m.get("rid") == ev["rid"]]
        assert row["classes"].get("misclassified_dependency_failure") is None or len(row["classes"]["misclassified_dependency_failure"]) <= len(
            plain["classes"].get("misclassified_dependency_failure", []))
    from r3_harness.h29 import aggregate
    assert aggregate.aggregate([row])["probes"]["lease_gap"] >= 1
    assert not next(q for q in plain["req"] if q["n"] == ev["n"])["lease_gap"]                  # known negative: no probe -> no gap


def test_g5_e28e_boundary_probe_matrix_known_negatives():
    """B1/B2 carry every shape; a probe answered OK / DENIED / UNKNOWN / INVALID-with-an-unmapped-reason makes the boundary non-explicit."""
    J = run("FakeHonestG5")
    ctx = _ctx(J)
    for b in ("B1", "B2"):
        raw = next(r for r in J["raws"] if r["stratum"] == "bnd" and (r["seq_def"] or {}).get("boundary") == b)
        row = judge.judge_seq(copy.deepcopy(raw), ctx)
        pr = row["boundary"].get("probes", [])
        assert {q["shape"] for q in pr} == set(rules.PROBE_SHAPES) and all(q["ok"] for q in pr) and row["boundary"]["explicit"], (b, pr)
        for res in ({"status": "OK", "body": {}}, {"status": "DENIED", "body": {"reason": "x"}}, {"status": "UNKNOWN", "body": {"reason": "unknown operation"}},
                    {"status": "INVALID", "body": {"reason": "zz_unmapped"}}):
            bad = copy.deepcopy(raw)
            e = [x for x in bad["events"] if x["k"] == "request" and x.get("invalid_probe") and x.get("probe_shape") == "unknown_tool"][-1]   # the matrix one
            e["res"] = res
            r2 = judge.judge_seq(bad, ctx)
            assert not r2["boundary"]["explicit"] and r2["classes"].get("boundary_not_explicit"), (b, res)


def test_g5_e28a_probe_answered_ok_without_a_commit_is_false_success():
    J = run("FakeHonestG5")
    raw, e = next((r, x) for r, x in _probe_events(J) if x.get("res"))
    bad = copy.deepcopy(raw)
    next(x for x in bad["events"] if x["n"] == e["n"])["res"] = {"status": "OK", "body": {}}
    assert judge.judge_seq(bad, _ctx(J))["classes"].get("false_success")
