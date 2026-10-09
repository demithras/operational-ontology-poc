"""G3 fix11 (attr5 of exp-h25-002): P-A total helpers over absent objects; P-B E32(a) decision tick on re-evaluation."""
import pytest

from paladin.domains.project.logic import facts, payloads
from paladin.domains.project.logic.policies import contract_complete
from r3_harness.h25 import boundary as B
from r3_harness.h25.gen_case import run_case
from r3_shared.registry import load_variant


def _classes(r):
    return set(r["classes"]) | set(r["case_classes"])


@pytest.mark.parametrize("i", [466, 2509])
def test_official_rows_match_oracle(i):
    assert "procedural_mismatch" not in _classes(run_case(load_variant("paladin", ()), 2520, i))


def test_boundary_flip_row_follows_oracle():
    out = B.flip_probe(load_variant("paladin", ()), 2520, 268)
    assert "procedural_mismatch" not in str(out), out


class _V:
    """A view with nothing in it: every object is absent/hidden."""
    def get(self, *a):
        return None

    def list(self, *a):
        return []

    def follow(self, *a, **k):
        return []


class _Ctx:
    def __init__(self, inputs):
        self.view, self.inputs = _V(), inputs


def test_new_experiment_ids_total_on_absent_experiment():
    old, new, ver, cv = payloads.new_experiment_ids(_V(), {"experiment": "NOPE", "contract_version": "CV-1"})
    assert (old, new, ver, cv) == ("NOPE", "NOPE@v.1", ".1", "CV-1+.1")


def test_contract_complete_total_when_experiment_props_absent(monkeypatch):
    class V(_V):
        pass
    monkeypatch.setattr(facts, "props", lambda v, t, k: {"claim": "c"} if t == "Hypothesis" else None)
    monkeypatch.setattr(facts, "out", lambda v, l, t, k: ["x"])
    monkeypatch.setattr(facts, "experiments_of", lambda v, h: ["E-gone"])
    assert contract_complete(V(), "H") is False


def test_latest_experiment_total_when_experiment_props_absent(monkeypatch):
    monkeypatch.setattr(facts, "experiments_of", lambda v, h: ["E-gone", "E2"])
    monkeypatch.setattr(facts, "props", lambda v, t, k: None if k == "E-gone" else {"version": "2"})
    assert facts.latest_experiment(_V(), "H") == "E2"


def test_compute_freeze_hash_total_on_absent_experiment():
    from paladin.domains.project.logic.freeze import compute_freeze_hash
    assert len(compute_freeze_hash(_V(), "NOPE")) == 64


def test_decision_content_hash_absent_decision_is_a_helper_error_not_a_type_error():
    from paladin.domains.manufacturing.logic.functions import decision_content_hash
    with pytest.raises(ValueError):
        decision_content_hash(_V(), {"decision": "NOPE"})
