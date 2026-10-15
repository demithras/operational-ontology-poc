import pytest

from r3_shared.verdict import Verdict, evaluate_from_mapping

KEYS = ["protocol_valid", "required_evidence_complete", "sample_sufficient", "reject_hit", "support_hit"]
GOOD = {"protocol_valid": True, "required_evidence_complete": True, "sample_sufficient": True,
        "reject_hit": False, "support_hit": True}
MISSING = object()


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("bad", [None, MISSING, "true", 1, 0])
def test_non_bool_never_supported(key, bad):
    m = dict(GOOD)
    if bad is MISSING:
        del m[key]
    else:
        m[key] = bad
    v = evaluate_from_mapping(m)
    assert v is not Verdict.SUPPORTED
    assert v is (Verdict.INVALID if key == "protocol_valid" else Verdict.INCONCLUSIVE)


def test_known_positive():
    assert evaluate_from_mapping(GOOD) is Verdict.SUPPORTED


def test_known_negative_reject():
    assert evaluate_from_mapping({**GOOD, "reject_hit": True}) is Verdict.REJECTED


def test_reported_case():
    m = {**GOOD, "reject_hit": None}
    assert evaluate_from_mapping(m) is Verdict.INCONCLUSIVE
