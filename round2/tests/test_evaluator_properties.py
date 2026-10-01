import pytest

try:
    from hypothesis import given, strategies as st
except ImportError:
    pytest.skip("hypothesis optional dependency not installed", allow_module_level=True)

from hdd.verdict import CommonEvaluation, Verdict, evaluate_common


@given(
    protocol_valid=st.booleans(),
    evidence=st.booleans(),
    sample=st.booleans(),
    reject=st.booleans(),
    support=st.booleans(),
)
def test_supported_is_never_default(protocol_valid, evidence, sample, reject, support):
    result = evaluate_common(CommonEvaluation(protocol_valid, evidence, sample, reject, support))
    if result is Verdict.SUPPORTED:
        assert protocol_valid
        assert evidence
        assert sample
        assert not reject
        assert support
