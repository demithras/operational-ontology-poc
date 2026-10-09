"""Known-negative fakes: each yields EXACTLY its expected class set (ORACLE-AND-HARNESS-G4 s8); FakeHonest yields none."""
import pytest

from tests.fakes import fake_h28
from tests.h28_util import run_corpus

CLASSES = ("effect_outside_scope", "false_reconciled_success", "governance_in_adapter", "duplicate_effect", "outcome_mismatch",
           "progress_loss")
EXPECT = {"FakeHonest": set(), "FakeTrustsReply": {"false_reconciled_success"}, "FakeRootCapToAdapter": {"effect_outside_scope"},
          "FakeAdapterPolicy": {"governance_in_adapter"}, "FakeFreshCapRetry": {"duplicate_effect"},
          "FakeReadsAdapterObservations": {"false_reconciled_success"}, "FakeAnyRowSuccess": {"false_reconciled_success", "outcome_mismatch"},  # R28-6 literal (PROT-H28 outranks the oracle-doc sketch)
         
          "FakeConsumesArtefact": {"governance_in_adapter", "effect_outside_scope"}, "FakeAlwaysUnknown": {"outcome_mismatch", "progress_loss"},
          "FakeNeverDispatch": {"progress_loss"}}
_cache = {}


def result(name):
    if name not in _cache:
        _cache[name] = run_corpus(lambda m, n=name: fake_h28.load(n, m))
    return _cache[name]


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_exact_class_set(name):
    J, agg, _, _ = result(name)
    got = {c for c in CLASSES if agg["classes"][c]["count"] or (c == "effect_outside_scope" and agg["unattributed_scope_rows"])}
    assert got == EXPECT[name], (name, {c: agg["classes"][c]["count"] for c in CLASSES}, agg["harness"])
    assert not agg["harness"], agg["harness"]


def test_honest_is_clean_and_detects_everything():
    J, agg, _, _ = result("FakeHonest")
    assert agg["detection"]["attempted"] > 0 and agg["detection"]["detected"] == agg["detection"]["attempted"]
    assert agg["floors"]["outcome_equal"] == agg["floors"]["outcome_points"] > 0
    assert agg["sysstate"]["replay_equals_sysstate"]
    assert all(v > 0 for v in agg["floors"]["controls_observed"].values())


@pytest.mark.parametrize("name", ["FakeTrustsReply", "FakeAnyRowSuccess"])
def test_detection_misses_for_trusting_fakes(name):
    _, agg, _, _ = result(name)
    assert agg["detection"]["detected"] < agg["detection"]["attempted"]


def test_governance_sub_kinds():
    assert result("FakeAdapterPolicy")[1]["governance_sub"].get("oracle_denied_variant_ok", 0) > 0
    assert result("FakeConsumesArtefact")[1]["governance_sub"].get("adapter_artefact_consumed", 0) > 0
