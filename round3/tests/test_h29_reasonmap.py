"""G5-E22: reason-map form r3-reason-map-1 (loader, schema, fixture) and its use by the judge (an unmapped raw reason while blocked = misclassification)."""
import copy
import json
from pathlib import Path

import pytest

from r3_harness.h29 import reasonmap
from r3_oracle import continuity as C

FIX = Path(__file__).parent / "fakes" / "h29_reason_map.json"


def test_fixture_loads_and_maps_per_variant():
    t = reasonmap.load(FIX)
    assert set(t) == {"fixture-a", "fixture-b"} and t["fixture-a"]["unknown_op"] == "unknown_operation"
    assert reasonmap.for_variant("fixture-b", FIX) == {"unknown operation": "unknown_operation"}


def test_absent_file_is_none_and_fakes_get_an_empty_table():
    assert reasonmap.load(FIX.parent / "nope.json") is None and reasonmap.for_variant("paladin", FIX.parent / "nope.json") == {}
    assert reasonmap.for_variant("FakeHonestG5", FIX) == {}


def test_real_variant_missing_from_a_present_file_raises():
    with pytest.raises(reasonmap.ReasonMapError):
        reasonmap.for_variant("paladin", FIX)


@pytest.mark.parametrize("mutate", [lambda d: d.update(form="r3-reason-map-2"), lambda d: d.update(extra=1), lambda d: d.pop("variants"),
                                    lambda d: d.update(variants={}), lambda d: d["variants"]["fixture-a"].update(x="not_a_class"),
                                    lambda d: d["variants"].update(bad=["x"])])
def test_schema_violations_are_rejected(mutate):
    d = copy.deepcopy(json.loads(FIX.read_text()))
    mutate(d)
    with pytest.raises(reasonmap.ReasonMapError):
        reasonmap.validate(d)


def test_unmapped_raw_reason_is_a_misclassification_and_mapped_is_admissible():
    cls = C.Cls(C.BLOCKED, ["AUTH"], True, "x")
    table = reasonmap.for_variant("fixture-a", FIX)
    assert C.blocked_reply_ok(cls, "INVALID", {"reason": "unknown_op"}, True, table)[0]
    assert not C.blocked_reply_ok(cls, "INVALID", {"reason": "something_new"}, True, table)[0]
    assert not C.blocked_reply_ok(cls, "INVALID", {"reason": "unknown_op"}, False, table)[0]


def test_real_reason_map_loads_and_covers_both_variants():
    """G5-E29(d): the auditor's real spec/gate5/reason-map.json is present, valid, and has a non-empty table per real variant."""
    assert reasonmap.DEFAULT_PATH.is_file()
    t = reasonmap.load()
    assert t is not None
    for v in reasonmap.REAL_VARIANTS:
        assert reasonmap.for_variant(v) and set(reasonmap.for_variant(v).values()) <= set(reasonmap.INPUT_INVALID_REASONS)
    assert reasonmap.for_variant("FakeHonestG5") == {}


def test_real_reason_map_loads_and_covers_both_variants():
    """G5-E29(d): the auditor's real spec/gate5/reason-map.json is present, valid, and has a non-empty table per real variant."""
    assert reasonmap.DEFAULT_PATH.is_file()
    assert reasonmap.load() is not None
    for v in reasonmap.REAL_VARIANTS:
        assert reasonmap.for_variant(v) and set(reasonmap.for_variant(v).values()) <= set(reasonmap.INPUT_INVALID_REASONS)
    assert reasonmap.for_variant("FakeHonestG5") == {}
