"""Generic reads: get, list, follow (both directions, cardinality), interface queries."""
import json
from pathlib import Path

import pytest

from eoo_engine import InvalidRequest, LoadError, required_bindings
from synth import build

ROOT = Path(__file__).resolve().parents[2]


def test_get_list_and_interface_query():
    eng, _, _ = build()
    v = eng.read_view()
    assert [o["key"] for o in v.list("Box")] == ["b1", "b2"]
    assert sorted((o["type"], o["key"]) for o in eng.interface_query("Labeled")) == \
        [("Box", "b1"), ("Box", "b2"), ("Shelf", "s1")]
    assert v.implementers("Labeled") == ("Box", "Shelf")
    assert eng.get("Labeled", "s1")["type"] == "Shelf" and eng.get("Box", "nope") is None
    with pytest.raises(InvalidRequest):
        v.list("NotAType")


def test_follow_both_directions_and_cardinality():
    eng, _, _ = build()
    assert eng.propose("shelve_box", {"box": "b1", "shelf": "s1"}, "filler")["state"] == "RECONCILED_SUCCESS"
    assert eng.propose("shelve_box", {"box": "b2", "shelf": "s1"}, "filler")["state"] == "RECONCILED_SUCCESS"
    v = eng.read_view()
    assert [o["key"] for o in v.follow("BoxOnShelf", "Box", "b1")] == ["s1"]
    assert sorted(o["key"] for o in v.follow("BoxOnShelf", "Shelf", "s1", "in")) == ["b1", "b2"]
    assert v.follow_one("BoxOnShelf", "Box", "b1")["key"] == "s1"
    with pytest.raises(InvalidRequest):
        v.follow_one("BoxOnShelf", "Shelf", "s1", "in")  # to-side max is 2, not single-valued
    eng2, _, _ = build()
    eng2.propose("make_box", {"key": "b3", "level": 0}, "filler")
    for b in ("b1", "b2"):
        assert eng2.propose("shelve_box", {"box": b, "shelf": "s1"}, "filler")["state"] == "RECONCILED_SUCCESS"
    h = eng2.state().state_hash()
    rec = eng2.propose("shelve_box", {"box": "b3", "shelf": "s1"}, "filler")  # shelf would hold 3 > max 2
    assert rec["state"] == "DENIED" and rec["gates"][-1]["gate"] == "integrity"
    assert eng2.state().state_hash() == h and eng2.effect_log.where(execution=rec["exec"]) == ()


def test_cardinality_report_lists_min_violations():
    eng, _, _ = build()
    assert eng.read_view().cardinality_report() == ()


@pytest.mark.parametrize("name", ["manufacturing-minimal.json", "project-domain-minimal.json"])
def test_examples_load_and_report_every_unbound_ref(name):
    pkg = json.loads((ROOT / "ontology" / "examples" / name).read_text())
    need = required_bindings(pkg)
    kinds = {u.kind for u in need}
    assert {"function", "policy", "constraint", "precondition", "outcome_predicate", "adapter"} <= kinds
    from eoo_engine import Engine
    with pytest.raises(LoadError) as ei:
        Engine(pkg)
    assert set(ei.value.problems) == set(need)


def test_openpona_coverage_ir_loads_with_full_unbound_report():
    pkg = json.loads((ROOT / "tests" / "h15" / "openpona_coverage_ir.json").read_text())
    need = required_bindings(pkg)
    assert need and all(isinstance(u.key, str) for u in need)  # '' is a legal (opaque) ref and still needs a binding
