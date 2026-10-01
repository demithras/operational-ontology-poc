import pytest

try:
    from hypothesis import given, strategies as st
except ImportError:
    pytest.skip("hypothesis optional dependency not installed", allow_module_level=True)

from hdd.project_lifecycle_reference import (
    HypothesisState, InvalidTransition, Phase, ScientificVerdict,
    attach_evidence, edit_threshold, evaluate, preregister, start, supersede,
)


def test_happy_path():
    s = preregister(HypothesisState(), "freeze")
    s = start(s)
    s = attach_evidence(s, commit_pinned=True)
    s = evaluate(s, ScientificVerdict.SUPPORTED)
    s = supersede(s)
    assert s.phase is Phase.SUPERSEDED


def test_threshold_immutable_after_preregistration():
    s = preregister(HypothesisState(), "freeze")
    with pytest.raises(InvalidTransition):
        edit_threshold(s)


def test_support_without_evidence_rejected():
    s = start(preregister(HypothesisState(), "freeze"))
    with pytest.raises(InvalidTransition):
        evaluate(s, ScientificVerdict.SUPPORTED)


@given(st.sampled_from([ScientificVerdict.SUPPORTED, ScientificVerdict.REJECTED]))
def test_evidenced_terminal_verdicts_require_at_least_one_record(verdict):
    s = start(preregister(HypothesisState(), "freeze"))
    with pytest.raises(InvalidTransition):
        evaluate(s, verdict)
