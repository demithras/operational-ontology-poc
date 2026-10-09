"""G3 fix9 (official exp-h25-001 / exp-h26-001 attribution): absent-target policy evaluation, blank freeze_hash, hidden fields."""
import pytest

from paladin.domains.project.logic import derive as D, facts
from paladin.domains.project.logic.policies import _incomplete, _threshold_edit_denied
from r3_harness.h25.gen_case import run_case
from r3_harness.h25.gen_race import Race
from r3_shared.registry import load_variant

# case id -> shape (report g3-attr4-h25): S1a absent threshold (execute), S1b evaluate_hypothesis on absent hypothesis,
# S2 record_decision on absent contract_version, S3 preregister_hypothesis with blank freeze_hash.
CASES = {615: "S1a", 2151: "S1a", 3159: "S1a", 4252: "S1a", 4798: "S1a", 5439: "S1a", 3471: "S1b", 4505: "S2",
         2195: "S3", 8812: "S3"}


def _classes(r):
    return set(r["classes"]) | set(r["case_classes"])


@pytest.mark.parametrize("i", sorted(CASES))
def test_official_h25_rows_match_oracle(i):
    r = run_case(load_variant("paladin", ()), 2510, i)
    assert "procedural_mismatch" not in _classes(r), (i, CASES[i], _classes(r))


def test_official_h25_race_row_matches_oracle():
    c = Race(load_variant("paladin", ()), 2510, 28, "EA_EDGE")
    c.script()
    out = c.env.judge()
    c.env.close()
    assert out["calls"], "no calls judged"
    bad = [(n, row["classes"]) for n, row in out["calls"].items() if "procedural_mismatch" in row["classes"]]
    assert not bad, bad


class _Ctx:
    def __init__(self, action, inputs, view):
        self.action, self.inputs, self.view = action, inputs, view


class _View:
    def __init__(self, hyps=None):
        self.hyps = hyps or {}

    def list(self, t):
        return [{"key": k, "props": p} for k, p in self.hyps.items()] if t == "Hypothesis" else []

    def get(self, t, k):
        return None


def test_threshold_edit_on_absent_threshold_is_denied_by_rule(monkeypatch):
    monkeypatch.setattr(facts, "hypotheses_of_threshold", lambda v, t: [])
    assert _threshold_edit_denied(_Ctx("edit_threshold", {"threshold": "NOPE"}, _View())) is True


def test_threshold_edit_on_draft_only_is_not_denied(monkeypatch):
    monkeypatch.setattr(facts, "hypotheses_of_threshold", lambda v, t: ["H"])
    assert _threshold_edit_denied(_Ctx("edit_threshold", {"threshold": "T"}, _View({"H": {"phase": "DRAFT"}}))) is False
    assert _threshold_edit_denied(_Ctx("edit_threshold", {"threshold": "T"}, _View({"H": {"phase": "RUNNING"}}))) is True


def test_blank_freeze_hash_is_not_a_deny_policy(monkeypatch):
    import paladin.domains.project.logic.policies as P
    monkeypatch.setattr(P, "contract_complete", lambda view, hid, freeze_hash=None: freeze_hash is None)
    assert _incomplete(_Ctx("preregister_hypothesis", {"hypothesis": "H", "freeze_hash": ""}, None)) is False


def test_derive_with_hidden_git_commit_has_null_semantics(monkeypatch):
    ev = {"experiment_version": 1, "payload_hash": "ph"}      # git_commit hidden == absent
    exp = {"version": 1, "evaluator_ref": "ev"}
    monkeypatch.setattr(facts, "props", lambda view, t, k: {"Hypothesis": {"freeze_hash": "f"}, "Experiment": exp,
                                                            "Evidence": ev}[t])
    monkeypatch.setattr(facts, "latest_experiment", lambda v, h: "E1")
    monkeypatch.setattr(facts, "evidence_of_experiment", lambda v, e: ["V1"])
    monkeypatch.setattr(facts, "evidence_count", lambda v, h: 1)
    ok = dict(protocol_valid=True, required_evidence_complete=True, sample_sufficient=True, reject_hit=False, support_hit=True)
    got = D.Deriver({"ev": lambda e, rows, h: ok}).derive(None, "H")
    assert got["verdict"] in ("SUPPORTED", "REJECTED", "INCONCLUSIVE", "INVALID")


def test_derive_with_hidden_evaluator_ref_does_not_raise(monkeypatch):
    monkeypatch.setattr(facts, "props", lambda view, t, k: {"Hypothesis": {"freeze_hash": "f"}, "Experiment": {"version": 1},
                                                            "Evidence": {"experiment_version": 1}}[t])
    monkeypatch.setattr(facts, "latest_experiment", lambda v, h: "E1")
    monkeypatch.setattr(facts, "evidence_of_experiment", lambda v, e: ["V1"])
    monkeypatch.setattr(facts, "evidence_count", lambda v, h: 1)
    assert D.Deriver({}).derive(None, "H")["verdict"] != "SUPPORTED"
