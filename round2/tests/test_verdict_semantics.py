from hdd.verdict import CommonEvaluation, Verdict, evaluate_common, h22_gate


def test_invalid_has_precedence():
    x = CommonEvaluation(False, True, True, True, True)
    assert evaluate_common(x) is Verdict.INVALID


def test_reject_has_precedence_over_support():
    x = CommonEvaluation(True, True, True, True, True)
    assert evaluate_common(x) is Verdict.REJECTED


def test_missing_evidence_never_supports():
    x = CommonEvaluation(True, False, True, False, True)
    assert evaluate_common(x) is Verdict.INCONCLUSIVE


def test_support_requires_explicit_support_hit():
    x = CommonEvaluation(True, True, True, False, False)
    assert evaluate_common(x) is Verdict.INCONCLUSIVE
    y = CommonEvaluation(True, True, True, False, True)
    assert evaluate_common(y) is Verdict.SUPPORTED


def test_h22_guard():
    assert not h22_gate(2, 1000)
    assert not h22_gate(3, 29)
    assert h22_gate(3, 30)
