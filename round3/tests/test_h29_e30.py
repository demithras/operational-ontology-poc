"""G5-E30 known-negatives: (a) input-invalid probes never eligible, (b) crash-armed request excluded by the corpus not the reply,
(c) generator during-fault share, (d) F6 stale request emitted, (e) anchor evidence indexed per worker, class detail rows in evidence."""
import copy
from concurrent.futures import ProcessPoolExecutor

import pytest

from r3_harness.h28.judge import LedgerIndex
from r3_harness.h29 import evidence_out, gen, judge
from tests.test_h29_fakes import run

SEEDS = (2911, 2912, 2921, 2922, 2923)


def _env_rows(J):
    return [r for r in J["rows"] if r["stratum"] == "env"]


def test_a_unknown_key_probe_is_never_progress_eligible():
    J = run("FakeHonestG5")
    probes = [q for r in _env_rows(J) for q in r["req"] if q.get("probe")]
    leak = [q for q in probes if q["probe_shape"] == "unknown_key" and q["oracle"] == "OK" and q["cls"] == "SAFE_TO_RUN" and q["strict"]]   # the lenient oracle calls these OK
    assert leak, "corpus has no unknown_key probe the lenient oracle decides OK: the known-negative is vacuous"
    assert all(q["input_invalid"] and not q["eligible"] for q in leak) and not any(q["eligible"] for q in probes)


def test_b_armed_request_is_excluded_by_the_corpus_whatever_the_reply():
    J = run("FakeHonestG5")
    ctx = judge.Ctx(LedgerIndex(J["services"]["merged"]), J["services"]["anchor"], None, dict(J["services"]["anchor_seq"]), workers=1)
    n = 0
    for raw in J["raws"]:
        keys = {e["key"] for e in raw["events"] if e["k"] == "crash_armed"}
        armed = [e for e in raw["events"] if e["k"] == "request" and e.get("rid") in keys]
        for e in armed:
            for res, err in (({"status": "OK", "body": {}}, None), (None, "no_reply")):       # a reply must never change eligibility
                R = copy.deepcopy(raw)
                ev = next(x for x in R["events"] if x["n"] == e["n"])
                ev["res"], ev["err"] = res, err
                row = judge.judge_seq(R, ctx)
                assert not [q for q in row["req"] if q.get("rid") == e["rid"] and q["eligible"]], (raw["seq"], e["rid"], err)
                n += 1
    assert n >= 4


def test_c_class_details_are_kept_in_the_evidence_rows():
    row = {"classes": {"unanchored_ack": [{"rid": "r7", "t": 4, "why": "no anchor entry"}], "forbidden_effect": [{"rid": "r1", "world_seq": 3, "oracle": "x"}]}}
    d = evidence_out.class_details(row)
    assert d["unanchored_ack"][0]["rid"] == "r7" and d["unanchored_ack"][0]["tick"] == 4 and d["unanchored_ack"][0]["what"] == "no anchor entry"
    assert d["forbidden_effect"][0]["what"] == "x"


def test_e_each_sequence_is_judged_against_its_own_workers_anchor():
    J = run("FakeHonestG5")
    ok = lambda r: r["req"] and r["classes"].get("unanchored_ack", []) == []          # noqa: E731
    raw = next(r for r in J["raws"] if r["stratum"] == "env" and r.get("stream") and any(
        e["k"] == "request" and (e.get("res") or {}).get("status") == "OK" for e in r["events"]))
    own = J["services"]["anchor_seq"][0]
    foreign = {k: [x + 1000 for x in v] for k, v in own.items()}                       # worker 1's anchor: same stream names, other sequence numbers
    anchors = {0: J["services"]["anchor"][0], 1: set(J["services"]["anchor"][0])}
    ctx = judge.Ctx(LedgerIndex(J["services"]["merged"]), anchors, None, {0: own, 1: foreign}, workers=2)
    mine, theirs = copy.deepcopy(raw), copy.deepcopy(raw)
    mine["j"], theirs["j"] = 0, 1                                                      # worker = j % workers
    assert ok(judge.judge_seq(mine, ctx))
    got = judge.judge_seq(theirs, ctx)["classes"].get("unanchored_ack", [])
    assert got, "a sequence run by worker 1 must NOT be satisfied by worker 0's entries (old merged index passed it)"
    merged = judge.Ctx(LedgerIndex(J["services"]["merged"]), anchors[0], None, own)      # single-anchor mode still works (unit tests)
    assert ok(judge.judge_seq(theirs, merged))


def _build_all(seed):
    st, out = {}, []
    for i in range(5600):
        h = gen.build("env", i, seed, st)
        out.append(h)
    return out


def _stale_missing(h):
    return h["classes"][0] == "F6" and (h["planned"]["stale_sensitive"] < 1 or not any(s.get("tag") == "stale" for s in h["steps"]))


@pytest.mark.parametrize("seed", SEEDS)
def test_c_d_generator_full_size_fault_share_and_f6_stale(seed):
    corpus = _build_all(seed)
    assert all(h is not None for h in corpus)
    tot = [sum(h["planned"]["fault_share"][k] for h in corpus) for k in (0, 1)]
    assert 100 * tot[1] >= 55 * tot[0], f"seed {seed}: plan-derived during-fault share {tot[1]}/{tot[0]} < 55%"
    f6 = [h for h in corpus if h["classes"][0] == "F6"]
    assert len(f6) == 700 and not [h["id"] for h in f6 if _stale_missing(h)]


def test_d_known_negative_env_000453_had_no_stale_request_before_the_fix():
    h = gen.build("env", 453, 2911, {})
    assert h["classes"][0] == "F6" and not _stale_missing(h)
    assert _stale_missing({"classes": ["F6"], "planned": {"stale_sensitive": 1}, "steps": [{"op": "request"}]})          # the old shape is detected
