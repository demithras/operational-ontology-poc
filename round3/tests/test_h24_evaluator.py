"""H24 evaluator: every contract clause, threshold and frozen floor on hand-built raw rows (no variant involved)."""
import copy
import gzip
import json
import subprocess
import sys
from pathlib import Path

import pytest

from r3_harness.h23.corpus import load_specs
from r3_harness.h24 import evaluator
from r3_harness.h24.analyze import RACE_FILE, SEQ_FILE, TYPES
from r3_harness.h24.runner import write_evidence
from r3_shared import mutants

ROUND3 = Path(__file__).resolve().parents[1]
TH = json.loads((ROUND3 / "protocol" / "thresholds.json").read_text())
SPECS = load_specs()
MUT_OK = {n: {"killed": True, "killing_class": "x"} for n in mutants.KNOWN["H24"]}


def row(kind="request", op="x", **kw):
    r = {"n": 0, "kind": kind, "op": op, "status": "OK", "committed": True, "must": True, "classes": ["ok"], "seq": 1,
         "tick": 0, "oracle": None, "lat_ms": 1.0, "depth": None, "intent": None}
    r.update(kw)
    return r


def good_corpus(n_seq=3, n_races=18):
    """A corpus that satisfies every clause: both domains, every op, depth >= 4, all race types, overlap, effect-first."""
    seqs = []
    for i in range(n_seq):
        d = ("manufacturing", "project")[i % 2]
        calls = [row("request", o["name"]) for o in SPECS[d][0]["operations"]]
        calls += [row("delegate", None, depth=k, intent="legal", oracle={"verdict": "OK", "reason": ""}) for k in (1, 4)]
        seqs.append({"id": f"seq-{i}", "domain": d, "digest": f"s{i}", "calls": calls, "case_classes": [], "max_depth": 4})
    cases = []
    for j in range(n_races):
        t = TYPES[j % len(TYPES)]
        cases.append({"id": f"race-{j}-{t}", "type": t, "domain": ("manufacturing", "project")[j % 2], "digest": f"r{j}",
                      "calls": [row()], "case_classes": [], "classes": ["ok"], "match": True,
                      "overlap": t != "SEQ", "order": "effect_first" if t == "RV" else None, "executed": t != "SEQ"})
    return seqs, cases


def write(tmp_path, seqs, cases, mut=None, name="fake-x", exp="exp-h24-dev"):
    out = tmp_path / exp / name
    out.mkdir(parents=True)
    with gzip.open(out / SEQ_FILE, "wt") as fh:
        for r in seqs:
            fh.write(json.dumps(r) + "\n")
    (out / RACE_FILE).write_text(json.dumps({"seed": 1, "cases": cases}))
    write_evidence(out, name, exp, 1, len(seqs), len(cases), MUT_OK if mut is None else mut)
    return out


def ev(out, **kw):
    kw.setdefault("min_sequences", 3)
    kw.setdefault("min_concurrent", 10)
    return evaluator.evaluate_variant(out, TH, out.name, **kw)


def test_clean_corpus_is_supported_only_through_recorded_dev_overrides(tmp_path):
    out = write(tmp_path, *good_corpus())
    r = ev(out)
    assert r["verdict"] == "SUPPORTED", r["reasons"]
    assert r["minimum_overrides"] == {"min_sequences": 3, "min_concurrent": 10}
    assert any(x.startswith("DEV ONLY") for x in r["reasons"])
    full = evaluator.evaluate_variant(out, TH, out.name)  # frozen minimums: 10,000 sequences / 1,000 cases
    assert full["verdict"] == "INCONCLUSIVE" and full["minimum_overrides"] == {}
    assert any("unique sequences" in x for x in full["reasons"])


def mutate(cases_or_seqs, which, cls, **extra):
    seqs, cases = good_corpus()
    tgt = seqs if which == "seq" else cases
    tgt[0]["calls"][0]["classes"] = [cls]
    tgt[0]["calls"][0].update(extra)
    return seqs, cases


@pytest.mark.parametrize("cls", ["scope_amplification", "post_boundary_effect", "forbidden_effect", "unattributed_write",
                                 "writer_violation", "unlogged_write", "cycle_grant", "linearizability_violation"])
def test_preregistered_falsifiers_reject(tmp_path, cls):
    seqs, cases = mutate(None, "seq", cls)
    assert ev(write(tmp_path, seqs, cases))["verdict"] == "REJECTED"


@pytest.mark.parametrize("cls", ["authority_ack_without_commit", "historical_mismatch", "progress_loss"])
def test_other_violations_block_support_but_are_not_rejects(tmp_path, cls):
    seqs, cases = mutate(None, "seq", cls)
    r = ev(write(tmp_path, seqs, cases))
    assert r["verdict"] == "INCONCLUSIVE" and any("support conditions unmet" in x for x in r["reasons"])


def test_case_level_classes_count_too(tmp_path):
    seqs, cases = good_corpus()
    seqs[0]["case_classes"] = ["unlogged_write"]
    assert ev(write(tmp_path, seqs, cases))["verdict"] == "REJECTED"


def test_race_that_does_not_match_the_oracle_blocks_support(tmp_path):
    seqs, cases = good_corpus()
    cases[0]["match"] = False
    r = ev(write(tmp_path, seqs, cases))
    assert r["verdict"] == "INCONCLUSIVE" and r["metrics"]["race_equality"] < 1.0


def test_floor_unaffected_legit_progress_below_one_is_inconclusive(tmp_path):
    seqs, cases = good_corpus()
    seqs[0]["calls"][0]["committed"] = False  # a must-commit request that did not commit (and nothing else flagged it)
    r = ev(write(tmp_path, seqs, cases))
    assert r["verdict"] == "INCONCLUSIVE" and any("unaffected-legit progress" in x for x in r["reasons"])


def test_floor_race_overlap_fraction_and_effect_first(tmp_path):
    seqs, cases = good_corpus()
    for c in cases:
        c["overlap"] = False  # the harness prevented every race from overlapping
    r = ev(write(tmp_path, seqs, cases, name="fake-a"), min_concurrent=0)
    assert r["verdict"] == "INCONCLUSIVE" and any("overlap fraction" in x for x in r["reasons"])
    seqs, cases = good_corpus()
    for c in cases:
        c["order"] = "revoke_first" if c["type"] == "RV" else None
    r = ev(write(tmp_path, seqs, cases, name="fake-b"))
    assert r["verdict"] == "INCONCLUSIVE" and any("effect-first" in x for x in r["reasons"])


def test_corpus_coverage_inconclusive_clauses(tmp_path):
    seqs, cases = good_corpus()
    cases = [c for c in cases if c["type"] != "EX"]
    r = ev(write(tmp_path, seqs, cases, name="fake-ex"))
    assert r["verdict"] == "INCONCLUSIVE" and any("EX" in x for x in r["reasons"])  # no expiry case
    seqs, cases = good_corpus()
    for s in seqs:
        for c in s["calls"]:
            c["depth"] = 1 if c["kind"] == "delegate" else None  # nothing nested to depth >= 4
    r = ev(write(tmp_path, seqs, cases, name="fake-depth"))
    assert r["verdict"] == "INCONCLUSIVE" and any("depth" in x for x in r["reasons"])
    seqs, cases = good_corpus(2, 18)  # one sequence per domain: dropping one domain's requests leaves its ops uncovered
    seqs[0]["calls"] = [c for c in seqs[0]["calls"] if c["kind"] != "request"]
    r = ev(write(tmp_path, seqs, cases, name="fake-op"))
    assert r["verdict"] == "INCONCLUSIVE" and any("not covered" in x for x in r["reasons"])
    r = ev(write(tmp_path, *good_corpus(2, 18), name="fake-few"), min_sequences=1000)
    assert r["verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("cls", ["unsupported", "world_lock_timeout"])
def test_unmeasurable_is_never_safe(tmp_path, cls):
    seqs, cases = mutate(None, "seq", cls)
    r = ev(write(tmp_path, seqs, cases))
    assert r["verdict"] == "INCONCLUSIVE" and any("unmeasurable" in x for x in r["reasons"])


def test_reject_outranks_inconclusive_and_mutation_proof_gates_support(tmp_path):
    seqs, cases = mutate(None, "seq", "unsupported")
    seqs[0]["calls"][1]["classes"] = ["scope_amplification"]
    assert ev(write(tmp_path, seqs, cases, name="fake-r"))["verdict"] == "REJECTED"
    partial = {**MUT_OK, "expiry_inclusive": {"killed": False}}
    r = ev(write(tmp_path, *good_corpus(), mut=partial, name="fake-m"))
    assert r["verdict"] == "INCONCLUSIVE" and r["metrics"]["mutation_kill_rate"] == 0.75
    missing = {k: v for k, v in MUT_OK.items() if k != "stale_authority_cache"}
    r = ev(write(tmp_path, *good_corpus(), mut=missing, name="fake-n"))
    assert r["verdict"] == "INCONCLUSIVE" and r["metrics"]["mutation_kill_rate"] is None  # missing evidence != SUPPORTED


def test_invalid_on_missing_evidence_tampered_file_and_semantic_drift(tmp_path):
    out = write(tmp_path, *good_corpus(), name="fake-i")
    f = out / "safe-progress.json"
    f.write_text(f.read_text() + " ")
    r = ev(out)
    assert r["verdict"] == "INVALID" and any("sha256 differs" in x for x in r["reasons"])
    out2 = write(tmp_path, *good_corpus(), name="fake-j")
    (out2 / "revocation-races.json").unlink()
    assert ev(out2)["verdict"] == "INVALID"
    out3 = write(tmp_path, *good_corpus(), name="fake-k")
    env = json.loads((out3 / "envelope.json").read_text())
    env["raw_observations"]["prot_h24_sha256"] = "0" * 64
    from r3_shared.evidence import sha256_of
    env.pop("payload_sha256")
    env["payload_sha256"] = sha256_of(env)
    (out3 / "envelope.json").write_text(json.dumps(env))
    r = ev(out3)
    assert r["verdict"] == "INVALID" and any("semantics changed" in x for x in r["reasons"])
    out4 = write(tmp_path, *good_corpus(), name="fake-l")
    s = json.loads((out4 / "authority-state-machine.json").read_text())
    s["class_counts"] = {"ok": 1}
    (out4 / "authority-state-machine.json").write_text(json.dumps(s))
    assert ev(out4)["verdict"] == "INVALID"  # (hash mismatch and summary-vs-raw disagreement)


def test_oracle_importing_a_variant_or_a_clock_is_invalid(tmp_path, monkeypatch):
    out = write(tmp_path, *good_corpus(), name="fake-o")
    monkeypatch.setattr(evaluator, "oracle_independent", lambda: (False, ["authority_v2.py: imports time"]))
    assert ev(out)["verdict"] == "INVALID"


def test_scan_catches_a_planted_clock_import_known_negative(tmp_path, monkeypatch):
    fake = tmp_path / "src" / "r3_oracle"
    fake.mkdir(parents=True)
    (fake / "authority_v2.py").write_text("import time\nfrom paladin import x\n")
    monkeypatch.setattr(evaluator, "ROUND3", tmp_path)
    ok, bad = evaluator.oracle_independent()
    assert not ok and any("imports time" in b for b in bad) and any("imports paladin" in b for b in bad)


def test_evaluate_script_refuses_overrides_on_non_dev_ids_and_stamps_dev_ones(tmp_path):
    out = write(tmp_path, *good_corpus(), exp="exp-h24-001")
    cmd = [sys.executable, str(ROUND3 / "scripts" / "evaluate_h24.py"), "exp-h24-001", "--out-root", str(tmp_path)]
    for flag in ("--min-sequences", "--min-concurrent"):
        r = subprocess.run([*cmd, flag, "3"], capture_output=True, text=True)
        assert r.returncode == 2 and "dev experiment" in r.stderr
    assert not (out.parent / "verdict.json").exists()
    assert subprocess.run(cmd, capture_output=True, text=True).returncode == 0  # no override: allowed (INCONCLUSIVE)
    v = json.loads((out.parent / "verdict.json").read_text())
    assert v["minimum_overrides"] == {} and v["hypothesis"] == "H24" and "evaluator_sha256" in v
    write(tmp_path, *good_corpus(), exp="exp-h24-dev2")
    r = subprocess.run([sys.executable, str(ROUND3 / "scripts" / "evaluate_h24.py"), "exp-h24-dev2", "--out-root", str(tmp_path),
                        "--min-sequences", "3", "--min-concurrent", "10"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    v = json.loads((tmp_path / "exp-h24-dev2" / "verdict.json").read_text())
    assert v["minimum_overrides"] == {"min_sequences": 3, "min_concurrent": 10}
    assert v["variants"]["fake-x"]["verdict"] == "SUPPORTED"
    _ = copy
