"""End-to-end H27 harness proof with fakes through scripts/run_h27.sh (anchor in a separate process, run under
sandbox-exec) and the contract evaluator. Dev minimums are lowered ONLY through evaluator parameters and are recorded."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from r3_harness.h27 import evaluator, runner
from r3_shared.anchor import start_anchor, verify_anchor_log

ROUND3 = Path(__file__).resolve().parents[1]
TH = json.loads((ROUND3 / "protocol" / "thresholds.json").read_text())
DEV = dict(min_tampered=100, min_bases=6, min_controls=20)
CFG = ["--seed", "1", "--per-domain", "6", "--tamper-cases", "160", "--controls", "20", "--decisions-max", "14",
       "--mutation-bases", "2", "--mutation-cases", "60", "--test-variants"]
VARIANTS = ["honest", "digest_omission", "fallback_to_current", "evidence_rebinding", "receipt_self_trust", "noanchor",
            "paranoid", "anchorwriter"]
ACCEPT = set(runner.__dict__.get("ACCEPT", ())) or {"tamper_accepted", "rebinding_accepted", "fallback_to_current",
                                                    "continuation_effect", "unanchored_ack"}


@pytest.fixture(scope="module")
def exp(tmp_path_factory):
    root = tmp_path_factory.mktemp("h27e2e")
    names = ",".join(f"fake-h27-{v}" for v in VARIANTS)
    p = subprocess.run([str(ROUND3 / "scripts" / "run_h27.sh"), "--exp-id", "exp-h27-dev", "--variants", names,
                        "--out-root", str(root), *CFG], capture_output=True, text=True, timeout=900)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
    return root / "exp-h27-dev"


@pytest.fixture(scope="module")
def verdicts(exp):
    return evaluator.evaluate_experiment(exp, TH, **DEV)["variants"]


def accepted(v):
    return {k for k in v["metrics"]["class_counts"] if k in ACCEPT}


def test_run_wrote_every_contract_evidence_file_and_a_sealed_envelope(exp):
    d = exp / "fake-h27-honest"
    for f in (*runner.FILES, "envelope.json", "expected-bindings.jsonl", "run-pre.json"):
        assert (d / f).is_file(), f
    env = json.loads((d / "envelope.json").read_text())
    ro = env["raw_observations"]
    assert ro["expected_bindings_sha256"] == hashlib.sha256((d / "expected-bindings.jsonl").read_bytes()).hexdigest()
    assert ro["canonical_bytes_source_sha256"] == evaluator.FROZEN_CANON_SHA
    assert (d / "anchor" / "anchor.log").is_file() and (d / "anchor" / "KEY.revealed").is_file()


def test_anchor_audit_records_all_five_enforcements_with_sandbox_level(exp):
    a = json.loads((exp / "fake-h27-honest" / "anchor-audit.json").read_text())
    assert a["E1_separate_process"] and a["anchor_pid"] != a["harness_pid"] and a["E2_key_only_at_close"]
    assert a["E3_holds"] and a["E3_enforcement"] == "sandbox-exec" and a["E4_all_denied"]
    assert set(a["E4_probe"].values()) == {"PermissionError"} and a["E5_log_integrity"]
    assert verify_anchor_log(exp / "fake-h27-honest" / "anchor", expected_head=a["closed_head"])["ok"]


def test_honest_fake_is_supported_only_through_recorded_dev_overrides(exp, verdicts):
    v = verdicts["fake-h27-honest"]
    assert v["verdict"] == "SUPPORTED", v["reasons"]
    assert v["metrics"]["detection_rate"] == 1.0 and not v["metrics"]["class_counts"]
    assert set(v["minimum_overrides"]) == {"min_tampered", "min_bases_per_domain", "min_controls"}
    assert any("DEV ONLY" in r for r in v["reasons"])
    full = evaluator.evaluate_variant(exp / "fake-h27-honest", TH, "fake-h27-honest")        # frozen minimums
    assert full["verdict"] == "INCONCLUSIVE" and "tampered cases" in " ".join(full["reasons"])


EXPECT = {"digest_omission": {"rebinding_accepted"}, "fallback_to_current": {"fallback_to_current"},
          "evidence_rebinding": {"rebinding_accepted"}, "receipt_self_trust": {"tamper_accepted", "rebinding_accepted"}}


@pytest.mark.parametrize("mutant", sorted(EXPECT))
def test_each_mutant_fake_is_rejected_with_exactly_its_accepted_class_set(verdicts, mutant):
    v = verdicts[f"fake-h27-{mutant}"]
    assert v["verdict"] == "REJECTED", v["reasons"]
    assert accepted(v) == EXPECT[mutant], v["metrics"]["class_counts"]
    assert v["metrics"]["detection_rate"] < 1.0


def test_honest_run_kills_every_h27_mutant_in_the_mutation_proof(verdicts):
    m = verdicts["fake-h27-honest"]["metrics"]
    assert m["mutation_kill_rate"] == 1.0 and all(m["mutants"].values()) and len(m["mutants"]) == 4


def test_a_fake_that_detects_nothing_new_survives_the_mutation_proof(verdicts):
    m = verdicts["fake-h27-paranoid"]["metrics"]       # always TAMPERED: never accepts, so no mutant can be 'killed'
    assert m["mutation_kill_rate"] == 0.0 and not any(m["mutants"].values())


def test_no_anchor_fake_is_rejected_for_unanchored_acks_never_supported(verdicts):
    v = verdicts["fake-h27-noanchor"]
    assert v["verdict"] == "REJECTED" and v["metrics"]["unanchored_ack"] > 0, v["reasons"]


def test_paranoid_fake_is_rejected_by_false_alarms_not_inconclusive_safe(verdicts):         # ruling Q8
    v = verdicts["fake-h27-paranoid"]
    assert v["verdict"] == "REJECTED" and v["metrics"]["false_alarms"] > 0 and v["metrics"]["accepted"] == 0
    assert v["metrics"]["detection_rate"] == 1.0


def test_anchor_writing_fake_is_blocked_by_the_sandbox_so_the_log_still_verifies(exp, verdicts):
    assert verdicts["fake-h27-anchorwriter"]["verdict"] == "SUPPORTED"
    assert verify_anchor_log(exp / "fake-h27-anchorwriter" / "anchor")["ok"]


def test_anchor_writing_fake_without_the_sandbox_is_INVALID_E3_E4_E5_fire(tmp_path):
    out = tmp_path / "exp-h27-dev" / "fake-h27-anchorwriter"
    out.mkdir(parents=True)
    sock = Path(tempfile.mkdtemp(prefix="r3s")) / "s"          # AF_UNIX paths are short
    ap = start_anchor(out / "anchor", sock)
    env = {**os.environ, "R3_ANCHOR_SOCK": str(sock), "R3_ANCHOR_DIR": str(out / "anchor"),
           "PYTHONPATH": str(ROUND3 / "src")}
    base = [sys.executable, str(ROUND3 / "scripts" / "run_h27.py"), "{mode}", "--exp-id", "exp-h27-dev", "--variant",
            "fake-h27-anchorwriter", "--out-root", str(tmp_path), *CFG]
    p = subprocess.run([a.replace("{mode}", "run") for a in base], env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-1500:]
    closed = ap.close()
    p = subprocess.run([a.replace("{mode}", "finalize") for a in base] + ["--closed-head", json.dumps(closed["head"])],
                       env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-1500:]
    au = json.loads((out / "anchor-audit.json").read_text())
    assert au["E3_holds"] is False and au["E4_all_denied"] is False and au["E3_enforcement"] == "none"
    assert au["E5_log_integrity"] is False                                   # the scribbled line broke the chain
    v = evaluator.evaluate_variant(out, TH, "fake-h27-anchorwriter", **DEV)
    assert v["verdict"] == "INVALID" and any("E3/E4" in r for r in v["reasons"]) and any("E5" in r for r in v["reasons"])


# ---- evaluator edge cases on copies of the honest evidence ---------------------------------------------------
@pytest.fixture()
def copy_honest(exp, tmp_path):
    dst = tmp_path / "fake-h27-honest"
    shutil.copytree(exp / "fake-h27-honest", dst)
    return dst


def reseal(d, monkeypatch=None):
    pre = json.loads((d / "run-pre.json").read_text())
    (d / "envelope.json").unlink()
    runner.seal(d, "exp-h27-dev", "fake-h27-honest", pre["seed"], pre, None)


def ev(d):
    return evaluator.evaluate_variant(d, TH, "fake-h27-honest", **DEV)


def test_missing_evidence_file_is_inconclusive_never_supported(copy_honest):
    (copy_honest / "historical-replay.json").unlink()
    v = ev(copy_honest)
    assert v["verdict"] == "INCONCLUSIVE" and "required evidence missing" in v["reasons"][0]


def test_edited_evidence_after_sealing_is_invalid(copy_honest):
    p = copy_honest / "mutation-results.json"
    p.write_text(p.read_text().replace('"killed": true', '"killed": false', 1))
    assert ev(copy_honest)["verdict"] == "INVALID"


def test_expected_bindings_must_be_hashed_before_tampering(copy_honest):
    env = json.loads((copy_honest / "envelope.json").read_text())
    (copy_honest / "envelope.json").unlink()
    from r3_shared import evidence
    ro = dict(env["raw_observations"], expected_bindings_sha256="0" * 64)
    new = evidence.build_envelope(experiment_id="exp-h27-dev", hypothesis_id="H27", git_commit=env["git_commit"],
                                  environment=env["environment"], seed=env["seed"], attack_class="A6",
                                  oracle_version=env["oracle_version"], candidate_version=env["candidate_version"], raw_observations=ro)
    evidence.write_envelope(copy_honest / "envelope.json", new)
    v = ev(copy_honest)
    assert v["verdict"] == "INVALID" and any("hashed before tampering" in r for r in v["reasons"])


def test_changed_canonicalization_is_invalid(copy_honest, monkeypatch):
    monkeypatch.setattr(runner, "CANON_SHA", "f" * 64)
    reseal(copy_honest)
    v = ev(copy_honest)
    assert v["verdict"] == "INVALID" and any("canonicalization" in r for r in v["reasons"])


def audit_edit(d, **kw):
    p = d / "anchor-audit.json"
    a = json.loads(p.read_text())
    a.update(kw)
    p.write_text(json.dumps(a))
    reseal(d)


def test_e1_failure_is_inconclusive_and_e3_failure_is_invalid(copy_honest, tmp_path):
    d2 = tmp_path / "e3"
    shutil.copytree(copy_honest, d2 / "x")
    audit_edit(copy_honest, E1_separate_process=False)
    v = ev(copy_honest)
    assert v["verdict"] == "INCONCLUSIVE" and any("E1/E2" in r for r in v["reasons"])
    audit_edit(d2 / "x", E3_holds=False)
    assert ev(d2 / "x")["verdict"] == "INVALID"


def test_tampered_anchor_log_copy_is_invalid_by_E5(copy_honest):
    log = copy_honest / "anchor" / "anchor.log"
    lines = log.read_bytes().split(b"\n")
    log.write_bytes(b"\n".join(lines[:5] + lines[6:]))                 # a deleted anchor entry
    v = ev(copy_honest)
    assert v["verdict"] == "INVALID" and any("E5" in r for r in v["reasons"])


def edit_cases(d, fn):
    p = d / "tamper-mutation-results.json"
    t = json.loads(p.read_text())
    t["cases"] = fn(t["cases"])
    p.write_text(json.dumps(t))
    reseal(d)


def test_absent_tamper_class_and_absent_compound_cases_are_inconclusive(copy_honest, tmp_path):
    d2 = tmp_path / "c" / "x"
    shutil.copytree(copy_honest, d2)
    edit_cases(copy_honest, lambda cs: [c for c in cs if "T7" not in c["applied"]])
    v = ev(copy_honest)
    assert v["verdict"] == "INCONCLUSIVE" and any("tamper classes absent" in r for r in v["reasons"])
    edit_cases(d2, lambda cs: [c for c in cs if len(c["classes"]) == 1])
    v = ev(d2)
    assert v["verdict"] == "INCONCLUSIVE" and any("compound" in r for r in v["reasons"])


def test_one_accepted_tamper_rejects_and_a_missing_mutant_key_is_inconclusive(copy_honest, tmp_path):
    d2 = tmp_path / "m" / "x"
    shutil.copytree(copy_honest, d2)

    def accept(cs):
        cs[0]["classes_hit"] = ["tamper_accepted"]
        return cs
    edit_cases(copy_honest, accept)
    assert ev(copy_honest)["verdict"] == "REJECTED"
    p = d2 / "mutation-results.json"
    m = json.loads(p.read_text())
    m.pop("digest_omission")
    p.write_text(json.dumps(m))
    reseal(d2)
    assert ev(d2)["verdict"] == "INCONCLUSIVE"


def test_unsupported_g2_methods_make_it_inconclusive(copy_honest):
    def unsup(cs):
        cs[0]["replays"][0]["classes"] = ["unsupported"]
        return cs
    edit_cases(copy_honest, unsup)
    v = ev(copy_honest)
    assert v["verdict"] == "INCONCLUSIVE" and any("unsupported" in r for r in v["reasons"])


def test_a_surviving_mutant_blocks_support(copy_honest):
    p = copy_honest / "mutation-results.json"
    m = json.loads(p.read_text())
    m["fallback_to_current"]["killed"] = False
    p.write_text(json.dumps(m))
    reseal(copy_honest)
    assert ev(copy_honest)["verdict"] == "INCONCLUSIVE"


def test_minimum_overrides_are_refused_for_non_dev_experiment_ids(exp, tmp_path):
    p = subprocess.run([sys.executable, str(ROUND3 / "scripts" / "evaluate_h27.py"), "exp-h27-001", "--out-root", str(tmp_path),
                        "--min-tampered", "10"], capture_output=True, text=True)
    assert p.returncode == 2 and "dev experiment ids" in p.stderr
    p = subprocess.run([sys.executable, str(ROUND3 / "scripts" / "evaluate_h27.py"), "exp-h27-dev", "--out-root", str(exp.parent),
                        "--min-tampered", "100", "--min-bases-per-domain", "6", "--min-controls", "20", "--print-only"],
                       capture_output=True, text=True)
    out = json.loads(p.stdout)
    assert out["minimum_overrides"] == {"min_tampered": 100, "min_bases_per_domain": 6, "min_controls": 20}
    assert out["variants"]["fake-h27-honest"]["verdict"] == "SUPPORTED"
    assert out["paladin_verdict"] == out["conventional_verdict"] == "INCONCLUSIVE"       # no real variant in this tree
    assert set(out["comparative"]) >= {"forbidden_effects", "safe_progress_ratio", "mutation_kill_rate", "p95_latency_ms"}


def test_unbuilt_real_variant_exits_2_with_the_honest_message(monkeypatch, capsys):
    """Both real variants are built since G2, so the unbuilt path is exercised by making the registry refuse (P12: the old
    subprocess form ran the full paladin run and timed out)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_h27_script", ROUND3 / "scripts" / "run_h27.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def refuse(name, mutants=()):
        raise NotImplementedError(f"variant {name!r} not implemented yet")
    monkeypatch.setattr(mod, "load_variant", refuse)
    with pytest.raises(SystemExit) as e:
        mod.factory_for("paladin", False)
    assert e.value.code == 2 and "not implemented yet - G2" in capsys.readouterr().err


def test_verify_script_reproduces_the_verdict(exp, tmp_path):
    out = subprocess.run([sys.executable, str(ROUND3 / "scripts" / "evaluate_h27.py"), "exp-h27-dev", "--out-root", str(exp.parent),
                          "--min-tampered", "100", "--min-bases-per-domain", "6", "--min-controls", "20"],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    env = {**os.environ, "R3_H27_OUT_ROOT": str(exp.parent), "PY": sys.executable}
    p = subprocess.run([str(ROUND3 / "scripts" / "verify_h27.sh"), "exp-h27-dev", "--min-tampered", "100",
                        "--min-bases-per-domain", "6", "--min-controls", "20"], capture_output=True, text=True, env=env)
    assert p.returncode == 0 and "verdict reproduces" in p.stdout, p.stdout + p.stderr
