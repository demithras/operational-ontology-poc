"""A8 (crash / restart / concurrency) harness proofs on fakes: known-positive, known-negative, evaluator coverage."""
import json
import shutil
from pathlib import Path

import pytest

from r3_harness.h23 import concurrency, crash_rules, evaluator
from r3_harness.h23.corpus import attack_sequence, load_specs, new_env
from r3_harness.h23.runner import A8_FILES, FILES, run_variant
from r3_oracle import serial
from tests.fakes.h23_fakes import FakeDep, FakeVariant, load

TH = json.loads((Path(__file__).resolve().parents[1] / "protocol" / "thresholds.json").read_text())
SPECS = load_specs()
N, MIN, CONC, MINC = 40, 30, 32, 24


def _classes(variant, rules, n=12, seed=11):
    out = []
    for i in range(n):
        rec = attack_sequence(variant, SPECS, seed, i, rules)
        out += [(c["rule"], k) for c in rec["calls"] for k in c["classes"]]
    return out


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    root = tmp_path_factory.mktemp("exp-a8")
    out = {"root": root}
    for name, mut in (("good", ()), ("volatile", ("ledger_after_commit_volatile",)),
                      ("unsync", ("unsynchronized_commit",))):
        out[name] = run_variant(lambda m, mu=mut: load("fake-correct", tuple(m) + mu), name, root / name, "exp-a8", 5,
                                N, mutation_sequences=40 if name == "good" else 1, concurrency_scenarios=CONC)
    return out


def _verdict(runs, name, minc=MINC):
    return evaluator.evaluate_variant(runs["root"] / name, TH, name, MIN, minc)


def test_correct_fake_has_no_a8_violation_and_every_crash_label_is_exercised(runs):
    a = runs["good"]["analysis"]
    assert a["class_counts"].get("crash_duplicate_effect", 0) == 0 and a["class_counts"].get("crash_state_mismatch", 0) == 0
    assert all(a["crash"].get(r, {}).get("calls") for r in crash_rules.REQUIRED)
    assert all(a["crash"][r]["triggered"] for r in crash_rules.REQUIRED if r.endswith(":armed"))
    v = _verdict(runs, "good")
    assert v["verdict"] == "SUPPORTED", v["reasons"]
    assert v["metrics"]["concurrency_unserializable"] == 0


def test_volatile_ledger_is_rejected_via_crash_duplicate_effect(runs):
    v = _verdict(runs, "volatile")
    assert v["verdict"] == "REJECTED" and v["metrics"]["crash_duplicate_effects"] > 0
    assert any(r == "crash_after:replay-same" for r, k in _classes(load("fake-correct", ["ledger_after_commit_volatile"]),
                                                                  ["crash_after"]) if k == "crash_duplicate_effect")


def test_unsynchronized_commit_is_rejected_via_concurrency_unserializable(runs):
    v = _verdict(runs, "unsync")
    assert v["verdict"] == "REJECTED" and v["metrics"]["concurrency_unserializable"] > 0
    assert v["metrics"]["forbidden_effects"] >= v["metrics"]["concurrency_unserializable"]


def test_new_mutants_are_killed_on_the_correct_fake_and_survive_on_a_variant_that_never_consults_them():
    from r3_harness.h23 import mutation
    got = mutation.prove(lambda m: load("fake-correct", m), SPECS, 24)
    assert got["ledger_after_commit_volatile"]["killed"] and got["unsynchronized_commit"]["killed"]
    assert got["unsynchronized_commit"]["first_counterexample"]["classes"] == ["concurrency_unserializable"]
    assert got["ledger_after_commit_volatile"]["shrunk_counterexample"]["steps"]
    dead = mutation.prove(lambda m: load("fake-deny-all", m), SPECS, 6)
    assert not dead["ledger_after_commit_volatile"]["killed"] and not dead["unsynchronized_commit"]["killed"]


class WrongStatusDep(FakeDep):
    def _run_locked(self, *a, **k):
        res = super()._run_locked(*a, **k)
        return res if res.status != "UNAVAILABLE" else type(res)("DENIED", {"reason": "no"})


class WrongStatusVariant(FakeVariant):
    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None):
        return WrongStatusDep("correct", domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=state_dir)


def test_a_crashed_deployment_that_answers_denied_instead_of_unavailable_is_a_state_mismatch():
    got = _classes(WrongStatusVariant("correct"), ["crash_before", "crash_after", "crash_idle"])
    assert any(r.endswith(":unavailable") and k == "crash_state_mismatch" for r, k in got)
    assert not any(k == "crash_duplicate_effect" for r, k in got)


class NoCrashDep(FakeDep):
    def arm_crash(self, point):
        raise NotImplementedError("arm_crash")

    def crash(self):
        raise NotImplementedError("crash")


class NoCrashVariant(FakeVariant):
    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None):
        return NoCrashDep("correct", domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=state_dir)


def test_variant_without_crash_support_is_inconclusive_never_supported(tmp_path):
    run_variant(lambda m: NoCrashVariant("correct", m), "nocrash", tmp_path / "v", "e", 5, N, mutation_sequences=1,
                concurrency_scenarios=CONC)
    v = evaluator.evaluate_variant(tmp_path / "v", TH, "nocrash", MIN, MINC)
    assert v["verdict"] == "INCONCLUSIVE" and any("crash_unsupported" in r for r in v["reasons"])


def _copy(runs, tmp_path):
    d = tmp_path / "v"
    shutil.copytree(runs["root"] / "good", d)
    return d


def _rehash(d):
    import hashlib

    from r3_shared import evidence
    old = json.loads((d / "envelope.json").read_text())
    raw = {f: hashlib.sha256((d / f).read_bytes()).hexdigest() for f in FILES + tuple(x for x in A8_FILES if (d / x).is_file())}
    (d / "envelope.json").unlink()
    evidence.write_envelope(d / "envelope.json", evidence.build_envelope(
        experiment_id="e", hypothesis_id="H23", git_commit="abcdefg1", environment={}, seed=1, attack_class="A1",
        oracle_version="o", candidate_version="c", raw_observations={"evidence_sha256": raw},
        freeze_hash=old["protocol_freeze_hash"]))


@pytest.mark.parametrize("how", ["missing", "empty", "no-approval-type", "no-same-k8", "too-few", "crash-missing"])
def test_evaluator_is_inconclusive_when_a8_coverage_is_absent(runs, tmp_path, how):
    d = _copy(runs, tmp_path)
    cf = d / A8_FILES[1]
    body = json.loads(cf.read_text())
    if how == "missing":
        cf.unlink()
    elif how == "crash-missing":
        (d / A8_FILES[0]).unlink()
    else:
        rows = body["scenarios"]
        if how == "empty":
            rows = []
        elif how == "no-approval-type":
            rows = [r for r in rows if r["type"] != "approval"]
        elif how == "no-same-k8":
            rows = [r for r in rows if not (r["type"] == "same" and r.get("k") == 8)]
        elif how == "too-few":
            rows = rows[:5]
        cf.write_text(json.dumps({"scenarios": rows}))
    _rehash(d)
    v = evaluator.evaluate_variant(d, TH, "x", MIN, MINC)
    assert v["verdict"] == "INCONCLUSIVE", (how, v["verdict"], v["reasons"])


def test_a8_files_with_a_wrong_hash_make_the_run_invalid(runs, tmp_path):
    d = _copy(runs, tmp_path)
    (d / A8_FILES[1]).write_text(json.dumps({"scenarios": []}))
    assert evaluator.evaluate_variant(d, TH, "x", MIN, MINC)["verdict"] == "INVALID"


def test_the_official_concurrency_minimum_is_300_unless_lowered_by_parameter(runs):
    assert evaluator.MIN_CONCURRENCY == 300
    assert evaluator.evaluate_variant(runs["root"] / "good", TH, "good", MIN)["verdict"] == "INCONCLUSIVE"


def test_serial_judge_accepts_each_serial_order_and_rejects_an_unexplained_world():
    env = new_env(FakeVariant("correct"), "project", SPECS, "serial")
    try:
        pool = concurrency._pool(env)
        x, y = pool["pairs"][0]
        reqs = [dict(pool["cands"][x], rid="r0"), dict(pool["cands"][y], rid="r1")]
        snap, now = env.snapshot(), env.clock.now()
        finals = {}
        for order in ((0, 1), (1, 0)):
            fin, _ = serial.simulate(env.ops, env.auth, snap, now, reqs, order)
            finals[order] = fin
            j = serial.judge(env.ops, env.auth, snap, now, reqs, fin)
            assert j["match"] == "full" and j["order"] in ([0, 1], [1, 0])
        assert serial.canon_world(finals[(0, 1)]) != serial.canon_world(finals[(1, 0)])
        assert serial.judge(env.ops, env.auth, snap, now, reqs, snap)["match"] == "subset"  # both refused
        bad = serial.apply_records(finals[(0, 1)], [{"kind": "update", "ref": next(iter(finals[(0, 1)]["objects"])),
                                                     "changes": {"phase": ["x", "zzz"]}}])
        assert serial.judge(env.ops, env.auth, snap, now, reqs, bad)["match"] is None
    finally:
        env.close()


def test_concurrency_scenarios_are_deterministic_and_cover_all_types_and_both_domains():
    a = [concurrency.scenario(FakeVariant("correct"), SPECS, 9, i) for i in range(16)]
    b = [concurrency.scenario(FakeVariant("correct"), SPECS, 9, i) for i in range(16)]
    key = lambda r: (r["type"], r["domain"], r.get("k"), [(q["op"], q["args"], q["rid"]) for q in r["requests"]])  # noqa: E731
    assert [key(r) for r in a] == [key(r) for r in b]
    s = concurrency.summarise(a)
    assert set(s["by_type"]) == set(concurrency.TYPES) and s["domains"] == ["manufacturing", "project"]
    assert s["concurrency_unserializable"] == 0 and s["executed"] >= 14
