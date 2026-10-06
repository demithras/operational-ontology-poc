"""Known-positive / known-negative proofs of the H23 harness using fakes (never registered)."""
import json
import random
from pathlib import Path

import pytest
from hypothesis import HealthCheck, settings
from hypothesis.stateful import run_state_machine_as_test

from r3_harness.h23 import evaluator
from r3_oracle import authority
from r3_harness.h23.analyze import analyze
from r3_harness.h23.corpus import attack_sequence, load_specs, run_corpus
from r3_harness.h23.env import Env
from r3_harness.h23.machine import make_machine
from r3_harness.h23.rules import exe, gen_step
from r3_harness.h23.chooser import RandChooser
from r3_harness.h23.runner import FILES, run_variant
from r3_shared import evidence, mutants
from r3_shared.verdict import evaluate_from_mapping
from tests.fakes.h23_fakes import FakeDep, FakeVariant, VARIANTS, load

TH = json.loads((Path(__file__).resolve().parents[1] / "protocol" / "thresholds.json").read_text())
N, MIN = 60, 50  # small corpus; the minimum is lowered ONLY here, via the evaluator parameter
SPECS = load_specs()


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("exp-h23-test")
    out = {}
    for name in VARIANTS:
        out[name] = run_variant(lambda m, n=name: load(n, m), name, root / name, "exp-h23-test", 7, N, mutation_sequences=40)
    out["root"] = root
    return out


def verdict(runs, name, min_sequences=MIN):
    return evaluator.evaluate_variant(runs["root"] / name, TH, name, min_sequences)


def test_allow_all_fake_is_rejected_with_forbidden_effects(runs):
    v = verdict(runs, "fake-allow-all")
    assert v["verdict"] == "REJECTED" and v["metrics"]["forbidden_effects"] > 0
    assert v["metrics"]["identity_expansions"] > 0


def test_correct_fake_is_supported_when_the_minimum_is_lowered_in_the_test_only(runs):
    v = verdict(runs, "fake-correct")
    assert v["verdict"] == "SUPPORTED", v["reasons"]
    m = v["metrics"]
    assert (m["forbidden_effects"], m["identity_expansions"], m["backstop_failures"]) == (0, 0, 0)
    assert m["safe_progress_ratio"] == 1.0 and m["mutation_kill_rate"] == 1.0 and m["backstop_rate"] == 1.0
    assert TH["H23"]["min_adversarial_sequences"] == 10000  # thresholds.json untouched


def test_correct_fake_is_inconclusive_at_the_real_minimum(runs):
    assert verdict(runs, "fake-correct", None)["verdict"] == "INCONCLUSIVE"


def test_hidden_tools_but_open_direct_is_rejected_via_backstop_failure(runs):
    v = verdict(runs, "fake-direct-open")
    assert v["verdict"] == "REJECTED" and v["metrics"]["backstop_failures"] > 0
    assert v["metrics"]["backstop_rate"] < 1.0


def test_deny_everything_fake_is_never_supported(runs):
    v = verdict(runs, "fake-deny-all")
    assert v["verdict"] != "SUPPORTED" and v["metrics"]["safe_progress_ratio"] == 0.0
    assert v["metrics"]["forbidden_effects"] == 0


def test_mutation_proof_kills_all_four_on_correct_fake_and_survives_when_switch_unconsulted(runs):
    good = json.loads((runs["root"] / "fake-correct" / "mutation-results.json").read_text())
    assert set(good) == set(mutants.KNOWN["H23"])
    assert all(e["killed"] for e in good.values())
    assert good["identity_substitution"]["shrunk_counterexample"]["steps"]
    dead = json.loads((runs["root"] / "fake-deny-all" / "mutation-results.json").read_text())
    assert all(not e["killed"] for e in dead.values())  # SURVIVED, not skipped


def test_unique_sequence_counting_ignores_duplicates_and_empty_steps(tmp_path):
    p = tmp_path / "s.jsonl"
    base = {"kind": "attack", "domain": "project", "attacker": "a", "calls": []}
    rows = [{**base, "seq_id": "1", "steps": [{"x": 1}], "hash": "h1"}, {**base, "seq_id": "2", "steps": [{"x": 1}], "hash": "h1"},
            {**base, "seq_id": "3", "steps": [{"x": 2}], "hash": "h2", "duplicate": True},
            {**base, "seq_id": "4", "steps": [], "hash": "h3"}]
    p.write_text("\n".join(json.dumps(r) for r in rows))
    assert analyze(p)["unique_sequences"] == 1  # h1 counted once; duplicate flag and empty steps excluded
    seen = [r["hash"] for r in run_corpus(VARIANTS["fake-correct"], SPECS, 20, 3, coverage=False)]
    assert len(set(seen)) == 20


def test_corpus_covers_every_operation_for_every_principal_and_a1_a2_a8(runs):
    a = analyze(runs["root"] / "fake-correct" / FILES[0])
    ops = {f"{d}:{o['name']}" for d in SPECS for o in SPECS[d][0]["operations"]}
    assert ops <= set(a["op_coverage"]) and all(a["a_class_calls"][c] > 0 for c in ("A1", "A2", "A8"))
    recs = [json.loads(x) for x in (runs["root"] / "fake-correct" / FILES[0]).read_text().splitlines()]
    cov = {(r["domain"], r["attacker"]) for r in recs if r["kind"] == "coverage"}
    for d in SPECS:
        assert {(d, p["id"]) for p in SPECS[d][1]["principals"]} <= cov


def test_evaluator_invalid_on_missing_evidence_hash_mismatch_and_inconclusive_on_missing_keys(runs, tmp_path):
    import shutil
    d = tmp_path / "v"
    shutil.copytree(runs["root"] / "fake-correct", d)
    (d / "direct-engine-backstop.json").unlink()
    assert evaluator.evaluate_variant(d, TH, "x", MIN)["verdict"] == "INVALID"
    shutil.rmtree(d)
    shutil.copytree(runs["root"] / "fake-correct", d)
    (d / "surface-audit.json").write_text("{\"rows\": [], \"overexposure\": 0}\n")
    assert evaluator.evaluate_variant(d, TH, "x", MIN)["verdict"] == "INVALID"  # sha256 differs from the envelope
    shutil.rmtree(d)
    shutil.copytree(runs["root"] / "fake-correct", d)
    mut = json.loads((d / "mutation-results.json").read_text())
    mut.pop("backstop_bypass")
    mut["tool_overexposure"]["killed"] = None
    _rewrite(d, mut=mut)
    assert evaluator.evaluate_variant(d, TH, "x", MIN)["verdict"] == "INCONCLUSIVE"  # missing mutant result


def _rewrite(d, mut=None, drop_rules=()):
    lines = [json.loads(x) for x in (d / FILES[0]).read_text().splitlines()]
    for r in lines:
        r["calls"] = [c for c in r["calls"] if c["rule"].split(":")[0].split("+")[0] not in drop_rules]
    (d / FILES[0]).write_text("\n".join(json.dumps(r, sort_keys=True, separators=(",", ":")) for r in lines) + "\n")
    if mut is not None:
        (d / FILES[4]).write_text(json.dumps(mut))
    a = analyze(d / FILES[0])
    s = json.loads((d / FILES[1]).read_text())
    s["class_counts"], s["unique_sequences"] = a["class_counts"], a["unique_sequences"]
    (d / FILES[1]).write_text(json.dumps(s))
    old = json.loads((d / "envelope.json").read_text())
    (d / "envelope.json").unlink()
    raw = {f: __import__("hashlib").sha256((d / f).read_bytes()).hexdigest() for f in FILES}
    env = evidence.build_envelope(experiment_id="e", hypothesis_id="H23", git_commit="abcdefg1", environment={}, seed=1,
                                  attack_class="A1", oracle_version="o", candidate_version="c",
                                  raw_observations={"evidence_sha256": raw}, freeze_hash=old["protocol_freeze_hash"])
    evidence.write_envelope(d / "envelope.json", env)


def test_evaluator_inconclusive_when_a8_missing(runs, tmp_path):
    import shutil
    d = tmp_path / "v"
    shutil.copytree(runs["root"] / "fake-correct", d)
    _rewrite(d, drop_rules={"replay", "replay_revoke", "toctou", "mutate_body"})
    v = evaluator.evaluate_variant(d, TH, "x", MIN)
    assert v["verdict"] == "INCONCLUSIVE" and any("A1/A2/A8" in r for r in v["reasons"])


def test_mapping_with_none_and_missing_keys_is_never_supported():
    assert evaluate_from_mapping(None).value == "INVALID"
    assert evaluate_from_mapping({"protocol_valid": True, "support_hit": True}).value == "INCONCLUSIVE"
    assert evaluate_from_mapping({"protocol_valid": True, "required_evidence_complete": True, "sample_sufficient": True,
                                  "reject_hit": None, "support_hit": True}).value == "INCONCLUSIVE"


def test_state_machine_passes_on_correct_fake_and_shrinks_a_failure_on_allow_all():
    cfg = settings(max_examples=25, stateful_step_count=6, deadline=None, database=None, derandomize=True,
                   suppress_health_check=list(HealthCheck))
    run_state_machine_as_test(make_machine(VARIANTS["fake-correct"], "project", SPECS), settings=cfg)
    with pytest.raises(AssertionError, match="effect outside the oracle"):
        run_state_machine_as_test(make_machine(VARIANTS["fake-allow-all"], "manufacturing", SPECS), settings=cfg)


class StaleAuthDep(FakeDep):
    def set_authority(self, auth):  # caches the old grants: a once-valid request keeps working after revocation
        pass


class StaleAuthVariant(FakeVariant):
    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock):
        return StaleAuthDep(self.mode, domain, factory, verifier, ops_spec, auth_spec, clock)


def _revoke_run(variant, seed):
    classes = []
    for i in range(30):
        rec = attack_sequence(variant, SPECS, seed, i, ["replay_revoke"])
        classes += [(c["rule"], k) for c in rec["calls"] for k in c["classes"]]
    return classes


def test_replay_after_revocation_catches_a_stale_authority_variant_and_passes_the_fallback():
    stale = _revoke_run(StaleAuthVariant("correct"), 5)
    assert any(r.startswith("replay_revoke:fresh-id") and k == "forbidden_effect" for r, k in stale)
    assert _revoke_run(FakeVariant("correct"), 5) == []


def test_set_authority_has_no_fallback_path_and_logs_versions():
    class Broken(FakeDep):
        def set_authority(self, auth):
            raise TypeError("signature differs")

    class BrokenVariant(FakeVariant):
        def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock):
            return Broken(self.mode, domain, factory, verifier, ops_spec, auth_spec, clock)

    env = Env(BrokenVariant("correct"), "project", *SPECS["project"], "t")
    try:
        with pytest.raises(TypeError):
            env.set_authority(env.auth)  # no silent redeploy
    finally:
        env.close()
    env = Env(FakeVariant("correct"), "project", *SPECS["project"], "t")
    try:
        entry = env.set_authority(authority.revoke(env.auth, "researcher-1", "attach_evidence"))
        assert entry["before"] != entry["after"] and env.authority_log == [entry]
    finally:
        env.close()
    rec = next(r for i in range(30) for r in [attack_sequence(FakeVariant("correct"), SPECS, 5, i, ["replay_revoke"])])
    assert rec["authority_version"]["changes"] and rec["authority_version"]["initial"] != rec["authority_version"]["final"]


def test_a_variant_without_a_class_attribute_audience_fails_explicitly():
    class NoAud(FakeVariant):
        audience = None

    with pytest.raises(RuntimeError, match="audience"):
        Env(NoAud("correct"), "project", *SPECS["project"], "t")


def test_toctou_flipdict_is_caught_when_the_variant_rereads_caller_args():
    mut = FakeVariant("correct", ["mutable_gated_input"])
    hits = [c for i in range(40) for c in attack_sequence(mut, SPECS, 9, i, ["toctou"])["calls"]
            if "forbidden_effect" in c["classes"]]
    assert hits and all("toctou" in c["tags"] for c in hits)
    assert not [c for i in range(40) for c in attack_sequence(FakeVariant("correct"), SPECS, 9, i, ["toctou"])["calls"]
                if c["classes"]]


def test_a_mutant_that_is_unknown_to_the_variant_is_rejected_and_one_never_consulted_survives():
    from r3_harness.h23 import mutation

    class Ignores(FakeVariant):  # accepts the mutant but never consults it anywhere
        def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock):
            return FakeDep(self.mode, domain, factory, verifier, ops_spec, auth_spec, clock, frozenset())

    res = mutation.prove(lambda m: Ignores("correct", m), SPECS, 20)
    assert set(res) == set(mutants.KNOWN["H23"]) and not any(e["killed"] for e in res.values())
    with pytest.raises(ValueError):
        FakeVariant("correct", ["nope"])
