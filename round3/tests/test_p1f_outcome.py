"""P1f-6 outcome vocabulary + form (validate_outcome exact keys/vocabulary). There is no outcome function in r3_shared."""
import copy

import pytest
from r3_shared import outcome as oc

GOOD = {"request_id": "r1", "effect_index": 0, "system": "ERP", "state": "RECONCILED_SUCCESS", "confidence": "full",
        "evidence": [3, 7]}


def test_vocabulary_is_frozen():
    assert oc.STATES == ("PENDING", "RECONCILED_SUCCESS", "RECONCILED_FAILED", "DIVERGED", "UNKNOWN")
    assert oc.CONFIDENCES == ("full", "low") and oc.KEYS == tuple(GOOD)
    assert not hasattr(oc, "outcome_state"), "the outcome function must not be shared code (ruling Q4)"


def test_good_outcome_validates_for_every_state():
    for st in oc.STATES:
        assert oc.validate_outcome({**GOOD, "state": st}) == {**GOOD, "state": st}
    oc.validate_outcome({**GOOD, "state": "UNKNOWN", "confidence": "low", "evidence": []})


@pytest.mark.parametrize("mut", [
    lambda o: o.pop("evidence"), lambda o: o.pop("system"), lambda o: o.update(extra=1),
    lambda o: o.update(state="SUCCESS"), lambda o: o.update(state="reconciled_success"), lambda o: o.update(state=None),
    lambda o: o.update(confidence="high"), lambda o: o.update(confidence=None),
    lambda o: o.update(effect_index=True), lambda o: o.update(effect_index=-1), lambda o: o.update(effect_index="0"),
    lambda o: o.update(request_id=""), lambda o: o.update(request_id=5),
    lambda o: o.update(evidence=[7, 3]), lambda o: o.update(evidence=[3, 3]), lambda o: o.update(evidence=[0]),
    lambda o: o.update(evidence=[True]), lambda o: o.update(evidence="3"), lambda o: o.update(evidence=[1.5]),
])
def test_outcome_form_known_negatives(mut):
    bad = copy.deepcopy(GOOD)
    mut(bad)
    with pytest.raises(oc.OutcomeFormError):
        oc.validate_outcome(bad)


def test_non_dict_refused():
    for x in (None, [], "x", 5):
        with pytest.raises(oc.OutcomeFormError):
            oc.validate_outcome(x)


def test_outcomes_body_sorted_unique():
    a, b = {**GOOD, "effect_index": 0}, {**GOOD, "effect_index": 1}
    assert oc.validate_outcomes({"outcomes": [a, b]}) == [a, b]
    assert oc.validate_outcomes({"outcomes": []}) == []
    for body in ({"outcomes": [b, a]}, {"outcomes": [a, a]}, {}, {"outcomes": "x"}, {"outcomes": [{**a, "state": "X"}]}):
        with pytest.raises(oc.OutcomeFormError):
            oc.validate_outcomes(body)


def test_transition_table():
    for p in ("PENDING", "UNKNOWN"):
        assert all(oc.allowed_transition(p, n) for n in oc.STATES)
    for p in oc.FINAL_STATES:
        assert oc.allowed_transition(p, p) and oc.allowed_transition(p, "DIVERGED")
        assert not any(oc.allowed_transition(p, n) for n in oc.STATES if n not in (p, "DIVERGED"))
    assert not oc.allowed_transition("DIVERGED", "RECONCILED_SUCCESS") and not oc.allowed_transition("X", "PENDING")
