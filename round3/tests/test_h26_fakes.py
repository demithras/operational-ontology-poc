"""H26 known-positive / known-negative tests with fakes (tests/fakes/fake_h26.py): pipeline end to end through the evaluator.
Minimums are lowered ONLY here (dev overrides, recorded in the verdict), never in thresholds.json."""
import json
from pathlib import Path

import pytest

from r3_harness.h26 import evaluator, mutation, runner
from r3_shared.mutants import KNOWN
from tests.fakes import fake_h26

ROOT = Path(__file__).resolve().parents[1]
TH = json.loads((ROOT / "protocol/thresholds.json").read_text())
DEV = {"min_pairs": 40, "min_aa": 10, "min_fuzz_calls": 300, "min_per_kind": 3, "min_per_channel": 10, "min_probes": 20}
_cache: dict = {}


def run_fake(tmp_path_factory, name):
    if name not in _cache:
        out = tmp_path_factory.mktemp(name) / "exp-h26-dev" / name
        runner.run_variant(lambda m, n=name: fake_h26.load(n, m), name, out, "exp-h26-dev", 1, 40, 10, 300, 12)
        _cache[name] = evaluator.evaluate_variant(out, TH, name, dev=True, ov=DEV), out
    return _cache[name]


def test_honest_fake_is_supported_on_a_small_corpus(tmp_path_factory):
    res, out = run_fake(tmp_path_factory, "fake-honest")
    assert res["verdict"] == "SUPPORTED", res["reasons"]
    assert res["metrics"]["mutation_kill_rate"] == 1.0 and res["metrics"]["leaks"] == {
        "divergence": 0, "existence_leak": 0, "value_exfiltration": 0, "provenance_overdisclosure": 0}
    assert "minimum_overrides" in res and res["minimum_overrides"]["min_pairs"] == 40


def test_overrides_refused_on_non_dev_ids(tmp_path_factory):
    _res, out = run_fake(tmp_path_factory, "fake-honest")
    assert evaluator.evaluate_variant(out, TH, "x", dev=False, ov=DEV)["verdict"] == "INVALID"


def test_frozen_minimum_is_not_met_by_the_small_corpus(tmp_path_factory):
    _res, out = run_fake(tmp_path_factory, "fake-honest")
    r = evaluator.evaluate_variant(out, TH, "fake-honest", dev=True, ov={})  # no overrides: 5,000 pairs required
    assert r["verdict"] == "INCONCLUSIVE" and any("valid pairs" in x for x in r["reasons"])


def test_nondeterministic_fake_is_inconclusive_via_aa(tmp_path_factory):
    res, _ = run_fake(tmp_path_factory, "fake-uuid")
    assert res["verdict"] in ("INCONCLUSIVE", "REJECTED") and res["verdict"] != "SUPPORTED"
    assert any("nondeterministic_output" in r or "divergence" in r for r in res["reasons"]), res["reasons"]


def test_deny_everything_fake_is_never_supported(tmp_path_factory):
    res, _ = run_fake(tmp_path_factory, "fake-denyall")
    assert res["verdict"] != "SUPPORTED"


def test_digest_leak_fake_is_flagged_on_decision_pairs():
    """FakeDigestLeak: an unredacted effect_digest. Decision-heavy corpus (kind D); the leak is a provenance_overdisclosure row
    and/or a noninterference divergence, which the evaluator maps to REJECTED."""
    from r3_harness.h26 import analyze, gen_pair, observe
    v = fake_h26.load("fake-digestleak")
    rows = []
    for i in range(60):
        p, _ = gen_pair.draw(32, i, kind="D")
        if p:
            rows.append(analyze.pair_row(p, [observe.run_world(v, p, w) for w in (0, 1)]))
    c = analyze.aggregate(rows)["counts"]
    assert c.get("provenance_overdisclosure", 0) > 0, c
    honest = fake_h26.load("fake-honest")
    rows = [analyze.pair_row(p, [observe.run_world(honest, p, w) for w in (0, 1)])
            for p in (gen_pair.draw(32, i, kind="D")[0] for i in range(20)) if p]
    assert analyze.aggregate(rows)["counts"].get("provenance_overdisclosure", 0) == 0


def test_every_h26_mutant_is_killed_by_the_subcorpus():
    m = mutation.prove(lambda mu: fake_h26.H26Variant(mu), 1, 12)
    assert set(m["mutants"]) == set(KNOWN["H26"])
    assert m["kill_rate"] == 1.0, {k: v["killed"] for k, v in m["mutants"].items()}
    for v in m["mutants"].values():
        assert v["killed"] and (v["first_counterexamples"] or v["fuzz_hit"])


def test_a_mutant_whose_switch_is_never_consulted_survives():
    class Inert(fake_h26.H26Variant):
        def __init__(self, mutants=()):
            super().__init__(())  # accepts the name, consults nothing
    m = mutation.prove(lambda mu: Inert(mu), 1, 6)
    assert m["kill_rate"] == 0.0 and not any(v["killed"] for v in m["mutants"].values())


@pytest.mark.parametrize("missing", ["noninterference-pairs.json", "exfiltration-fuzz.json", "mutation-results.json", "envelope.json"])
def test_missing_evidence_is_never_supported(tmp_path_factory, missing):
    import shutil
    _res, out = run_fake(tmp_path_factory, "fake-honest")
    cp = tmp_path_factory.mktemp("cp") / "exp-h26-dev" / "fake-honest"
    shutil.copytree(out, cp)
    (cp / missing).unlink()
    r = evaluator.evaluate_variant(cp, TH, "fake-honest", dev=True, ov=DEV)
    assert r["verdict"] != "SUPPORTED" and any("missing" in x for x in r["reasons"])


def test_tampered_evidence_hash_is_invalid(tmp_path_factory):
    import shutil
    _res, out = run_fake(tmp_path_factory, "fake-honest")
    cp = tmp_path_factory.mktemp("cp2") / "exp-h26-dev" / "fake-honest"
    shutil.copytree(out, cp)
    p = cp / "safe-progress.json"
    p.write_text(p.read_text() + " ")
    assert evaluator.evaluate_variant(cp, TH, "fake-honest", dev=True, ov=DEV)["verdict"] == "INVALID"


def test_evaluator_none_and_empty_mappings_are_not_supported():
    from r3_shared.verdict import evaluate_from_mapping
    assert evaluate_from_mapping(None).value == "INVALID" and evaluate_from_mapping({}).value == "INVALID"
    assert evaluate_from_mapping({"protocol_valid": True}).value == "INCONCLUSIVE"
