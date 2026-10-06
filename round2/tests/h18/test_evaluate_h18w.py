"""H18w evaluator: a known-positive is SUPPORTED; for EACH support / reject / inconclusive / invalid clause a known-negative flips it."""
import json
import shutil
import subprocess

import pytest

from eoo_exp import provenance as prov
from eoo_exp.util import canon, sha_text
from eoo_h18.evaluate_w import dirty_harness_files, evaluate, paths_differing_from_tag

CLEAN = {"engine_diff": lambda p: [], "oracle_diff": lambda p: []}


def vals(v):
    return {r["id"]: r["value"] for rows in v["predicates"].values() for r in rows}


def flipped(base, v):
    b, x = vals(base), vals(v)
    return sorted(k for k in b if b[k] != x[k])


@pytest.fixture(scope="module")
def clean_pos(positive_dir, tmp_path_factory):
    """The H18 known-positive with the run's dirtiness cleared (a real dev run has a dirty tree; the authoritative one does not)."""
    dst = tmp_path_factory.mktemp("h18w") / "pos"
    shutil.copytree(positive_dir, dst)
    for f in dst.glob("*.json"):
        if f.name == "verdict.json":
            continue
        rec = json.loads(f.read_text())
        rec["harness_dirty"], rec["harness_dirty_paths"] = False, []
        prov.write(dst, f.name, rec)
    return dst


@pytest.fixture(scope="module")
def base(clean_pos):
    return evaluate(clean_pos, **CLEAN)


@pytest.fixture()
def wedit(clean_pos, tmp_path):
    n = [0]

    def _edit(filename=None, fn=None, record_fn=None, drop=None):
        n[0] += 1
        dst = tmp_path / f"ev{n[0]}"
        shutil.copytree(clean_pos, dst)
        if drop:
            (dst / drop).unlink()
        if filename:
            rec = json.loads((dst / filename).read_text())
            if fn:
                fn(rec["payload"])
                rec["payload_hash"] = sha_text(canon(rec["payload"]))
            if record_fn:
                record_fn(rec)
            prov.write(dst, filename, rec)
        return dst
    return _edit


def _step(p, **kw):
    s = p["cases"][0]["steps"][0]
    return s


def test_known_positive_is_supported(base):
    assert base["verdict"] == "SUPPORTED", (base["verdict"], base["problems"], vals(base), base["protocol_mismatches"], base["numbers"]["harness_self_check"])
    v = vals(base)
    assert sorted(v) == ["I", "R", "S1", "S1b", "S2", "S3", "S4", "S6", "V1", "V2", "V3", "V4", "V5", "V6"]
    assert [k for k, x in v.items() if k[0] == "S" and x is not True] == [] and [k for k, x in v.items() if k[0] in "RIV" and x is not False] == []
    assert base["hypothesis_id"] == "H18w" and base["post_hoc"] is True and base["numbers"]["unique_cases"] == 3000


def test_S1_illegal_accepted_in_an_extension_class_is_not_support(base, wedit):
    def f(p):
        s = _step(p)
        s["cls"], s["legal"] = ["supersede_self"], False
        s["eoo"].update(acc=True, div="illegal_accepted")
    v = evaluate(wedit("project-state-machine.json", f), **CLEAN)
    assert vals(v)["S1"] is False and vals(v)["S1b"] is True and vals(v)["R"] is True and v["verdict"] == "REJECTED"
    assert v["numbers"]["illegal_accepted_by_class"] == {"supersede_self": 1, "*": 1} or v["numbers"]["illegal_accepted_by_class"].get("supersede_self") == 1


def test_S1b_a_legal_step_refused_is_not_support(base, wedit):
    def f(p):
        s = _step(p)
        s["cls"], s["legal"] = ["new_version_chain"], True
        s["eoo"].update(acc=False, div="legal_rejected", commits=0)
    v = evaluate(wedit("project-state-machine.json", f), **CLEAN)
    assert vals(v)["S1"] is True and vals(v)["S1b"] is False and "S1b" in flipped(base, v) and v["verdict"] == "REJECTED" and vals(v)["R"] is True
    assert v["numbers"]["legal_rejected_by_class"].get("new_version_chain") == 1


def test_S1b_a_state_mismatch_is_not_support(base, wedit):
    v = evaluate(wedit("project-state-machine.json", lambda p: _step(p)["eoo"].update(match=False)), **CLEAN)
    assert vals(v)["S1b"] is False and v["verdict"] == "REJECTED"


def test_S1_a_refused_op_that_reached_git_is_not_support(base, wedit):
    def f(p):
        s = _step(p)
        s["eoo"].update(acc=False, commits=1)
    v = evaluate(wedit("project-state-machine.json", f), **CLEAN)
    assert vals(v)["S1"] is False and v["verdict"] != "SUPPORTED"


def test_R_core_illegal_accepted_is_rejected(base, wedit):
    def f(p):
        s = _step(p)
        s["cls"], s["legal"] = ["post_freeze_threshold_edit"], False
        s["eoo"].update(acc=True, div="illegal_accepted")
    v = evaluate(wedit("project-state-machine.json", f), **CLEAN)
    assert v["verdict"] == "REJECTED" and vals(v)["R"] is True and {"S1", "R"} <= set(flipped(base, v))


def test_S4_domain_branch_in_the_engine_is_rejected(base, wedit):
    def f(p):
        p["engine_domain_audit"]["project_domain_branches"] = 1
        p["engine_domain_audit"]["domain_identity_branches"] = 1
    v = evaluate(wedit("project-state-machine.json", f), **CLEAN)
    assert v["verdict"] == "REJECTED" and vals(v)["S4"] is False and vals(v)["R"] is True and flipped(base, v) == ["R", "S4"]


def test_R_hostile_dogfood_step_accepted_is_rejected(base, wedit):
    def f(p):
        p["dogfood_steps"][0]["expected_accept"] = not p["dogfood_steps"][0]["accepted"]
    v = evaluate(wedit("verdict-reproducibility.json", f), **CLEAN)
    assert vals(v)["R"] is True and v["verdict"] == "REJECTED"


def test_S3_untraced_commit_or_ontology_only_write_blocks_support(base, wedit):
    v = evaluate(wedit("project-state-machine.json", lambda p: _step(p)["eoo"].update(trace=False)), **CLEAN)
    assert vals(v)["S3"] is False and v["verdict"] == "REJECTED"
    v = evaluate(wedit("project-state-machine.json", lambda p: _step(p)["eoo"].update(unchanged=False)), **CLEAN)
    assert vals(v)["S3"] is False and v["verdict"] == "REJECTED"


def test_S2_authoritative_verdict_not_reproducible_blocks_support(base, wedit):
    v = evaluate(wedit("verdict-reproducibility.json", lambda p: p["authoritative"].update(reproducible=False)), **CLEAN)
    assert flipped(base, v) == ["S2"] and v["verdict"] == "INCONCLUSIVE"  # the prereg names no reject clause for S2


def test_S6_a_surviving_target_mutant_blocks_support(base, wedit):
    def f(p):
        next(m for m in p["mutants"] if m["id"] == "M3_detach_commit_provenance").update(killed=False)
    v = evaluate(wedit("mutation-results.json", f), **CLEAN)
    assert flipped(base, v) == ["S6"] and v["verdict"] == "INCONCLUSIVE" and v["numbers"]["target_mutants"]["M3_detach_commit_provenance"] is False


def test_S6_a_missing_named_target_mutant_blocks_support(base, wedit):
    v = evaluate(wedit("mutation-results.json", lambda p: p.update(mutants=[m for m in p["mutants"] if m["id"] != "M2_allow_verdict_without_evidence"])), **CLEAN)
    assert vals(v)["S6"] is False and v["verdict"] != "SUPPORTED"


def test_I_too_few_unique_sequences_is_inconclusive(base, wedit):
    v = evaluate(wedit("project-state-machine.json", lambda p: p.update(cases=p["cases"][:100])), **CLEAN)
    assert v["verdict"] == "INCONCLUSIVE" and {"I", "S1"} <= set(flipped(base, v))


def test_I_a_hostile_edit_class_never_generated_is_inconclusive(base, wedit):
    def f(p):
        for c in p["cases"]:
            c["steps"] = [s for s in c["steps"] if "flag_non_orphan" not in s["cls"]]
    v = evaluate(wedit("project-state-machine.json", f), **CLEAN)
    assert v["verdict"] == "INCONCLUSIVE" and flipped(base, v) == ["I"]


def test_V1_wrong_protocol_or_prereg_hash_is_invalid(base, wedit):
    v = evaluate(wedit("git-traceability.json", record_fn=lambda r: r.update(protocol_freeze_hash="0" * 64)), **CLEAN)
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V1"]
    v = evaluate(wedit("git-traceability.json", record_fn=lambda r: r.update(engine_prereg_sha256="0" * 64)), **CLEAN)
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V1"]


def test_V2_disagreeing_provenance_or_other_engine_version_is_invalid(base, wedit):
    v = evaluate(wedit("baseline-comparison.json", record_fn=lambda r: r.update(seed=999)), **CLEAN)
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V2"]
    v = evaluate(wedit("baseline-comparison.json", record_fn=lambda r: r.update(engine_version="1.1")), **CLEAN)
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V2"]


def test_V3_engine_differs_from_r2_engine_v1_2_is_invalid(base, clean_pos):
    v = evaluate(clean_pos, engine_diff=lambda p: ["round2/src/eoo_engine/policy.py"], oracle_diff=lambda p: [])
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V3"]
    assert v["numbers"]["engine_paths_differing_from_tag"] == ["round2/src/eoo_engine/policy.py"] and vals(v)["S1"] is True


def test_V4_oracle_changed_is_invalid(base, clean_pos):
    v = evaluate(clean_pos, engine_diff=lambda p: [], oracle_diff=lambda p: ["round2/oracles/h18/world.py"])
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V4"]


def test_V5_harness_dirty_at_run_time_is_invalid(base, wedit):
    def r(rec):
        k = sorted(f for f in rec["harness_sha256"] if f.startswith("src/eoo_h18/") and f != "src/eoo_h18/evaluate_w.py")[0]
        rec["harness_dirty"], rec["harness_dirty_paths"] = True, ["round2/" + k]
    v = evaluate(wedit("project-state-machine.json", record_fn=r), **CLEAN)
    assert v["verdict"] == "INVALID" and flipped(base, v) == ["V5"] and v["numbers"]["harness_dirty_files_at_run"]


def test_V5_ignores_dirt_outside_the_harness(base, wedit):
    v = evaluate(wedit("project-state-machine.json", record_fn=lambda r: r.update(harness_dirty=True, harness_dirty_paths=["round2/docs/notes.md", "scratch/x"])), **CLEAN)
    assert vals(v)["V5"] is False and v["verdict"] == "SUPPORTED"


def test_V6_self_check_failures_are_invalid(base, wedit):
    v = evaluate(wedit("mutation-results.json", lambda p: p["controls"].update(clean=False)), **CLEAN)
    assert v["verdict"] == "INVALID" and vals(v)["V6"] is True
    v = evaluate(wedit("project-state-machine.json", lambda p: _step(p)["eoo"].update(exc="KeyError: x")), **CLEAN)
    assert v["verdict"] == "INVALID" and vals(v)["V6"] is True

    def r(rec):
        rec["harness_sha256"][sorted(rec["harness_sha256"])[0]] = "0" * 64
    v = evaluate(wedit("project-state-machine.json", record_fn=r), **CLEAN)
    assert v["verdict"] == "INVALID" and vals(v)["V6"] is True
    v = evaluate(wedit("project-state-machine.json", lambda p: p["oracle"]["oracle_import_audit"].update(independent=False)), **CLEAN)
    assert v["verdict"] == "INVALID" and vals(v)["V6"] is True


def test_summary_disagreeing_with_rows_is_a_problem(base, wedit):
    v = evaluate(wedit("project-state-machine.json", lambda p: p["eoo"].update(legal_rejected=5)), **CLEAN)
    assert v["problems"] and v["verdict"] != "SUPPORTED"


def test_missing_or_tampered_evidence_never_supports(wedit, clean_pos, tmp_path):
    v = evaluate(wedit(drop="mutation-results.json"), **CLEAN)
    assert v["verdict"] != "SUPPORTED" and any("mutation-results.json: missing" in p for p in v["problems"])
    dst = tmp_path / "t"
    shutil.copytree(clean_pos, dst)
    rec = json.loads((dst / "mutation-results.json").read_text())
    rec["payload"]["mutants"][0]["killed"] = False  # hash NOT refreshed
    (dst / "mutation-results.json").write_text(json.dumps(rec))
    v = evaluate(dst, **CLEAN)
    assert v["verdict"] != "SUPPORTED" and any("payload_hash" in p for p in v["problems"])


def test_dirty_harness_files_helper():
    rec = {"harness_sha256": {"src/eoo_h18/rig.py": "a", "baselines/h18_fileonly/x.py": "b", "src/eoo_h18/evaluate_w.py": "c"},
           "harness_dirty_paths": ["round2/baselines/", "round2/src/eoo_h18/evaluate_w.py", "other/src/eoo_h18/rig.py"]}
    assert dirty_harness_files(rec) == ["baselines/h18_fileonly/x.py"]


def test_engine_diff_against_a_tag_in_a_real_repo(tmp_path):
    """Known-positive/negative of the real tag check, in a throwaway repo (never the project repository)."""
    def g(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    g("init", "-q")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (tmp_path / "e").mkdir()
    (tmp_path / "e" / "a.py").write_text("x = 1\n")
    g("add", "-A")
    g("commit", "-qm", "init")
    g("tag", "r2-engine-v1.2")
    assert paths_differing_from_tag(("e",), repo=tmp_path) == []
    (tmp_path / "e" / "a.py").write_text("x = 2\n")
    assert paths_differing_from_tag(("e",), repo=tmp_path) == ["e/a.py"]
    g("checkout", "-q", "--", "e/a.py")
    (tmp_path / "e" / "new.py").write_text("y = 1\n")
    assert paths_differing_from_tag(("e",), repo=tmp_path) == ["e/new.py"]
    assert paths_differing_from_tag(("e",), tag="nope", repo=tmp_path) == ["tag nope not found"]


def test_the_real_engine_and_oracle_match_tag_r2_engine_v1_2_now():
    from eoo_h18.evaluate_w import ENGINE_PATHS, ORACLE_PATHS
    assert paths_differing_from_tag(ENGINE_PATHS) == [] and paths_differing_from_tag(ORACLE_PATHS) == []
