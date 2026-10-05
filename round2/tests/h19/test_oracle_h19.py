"""The H19 oracle: a pure immutable commit DAG + deterministic projection. Unit tests of its semantics and of its independence."""
import copy

import pytest

from eoo_h19.independence import oracle_imports
from eoo_h19.oracle import M

BASE = {"obj|Threshold|t1": {"id": "t1", "value": 1}, "obj|Component|c1": {"id": "c1", "path": "p", "orphan_flagged": False}}


def ch(e, **props):
    return {"e": e, "props": props}


def test_projection_hash_is_order_free_and_content_sensitive():
    a = {"x": {"v": 1}, "y": {"v": 2}}
    assert M.state_hash(a) == M.state_hash({"y": {"v": 2}, "x": {"v": 1}})
    assert M.state_hash(a) != M.state_hash({"x": {"v": 1}, "y": {"v": 3}})


def test_commits_are_immutable_and_a_fresh_write_appends():
    d = M.Dag(BASE)
    h0 = d.hash(0)
    o = d.write(0, [ch("obj|Threshold|t1", value=2)])
    assert o.kind == "ok" and d.head == 1 and d.hash(0) == h0 and d.state(1)["obj|Threshold|t1"]["value"] == 2


def test_stale_compatible_write_merges_and_keeps_both_changes():
    d = M.Dag(BASE)
    d.write(0, [ch("obj|Threshold|t1", value=2)])
    o = d.write(0, [ch("obj|Component|c1", path="q")])
    assert o.kind == "ok" and "compatible_concurrent" in o.classes
    assert d.state(d.head)["obj|Threshold|t1"]["value"] == 2 and d.state(d.head)["obj|Component|c1"]["path"] == "q"


def test_same_property_different_values_is_an_explicit_conflict_that_changes_nothing():
    d = M.Dag(BASE)
    d.write(0, [ch("obj|Threshold|t1", value=2)])
    h = d.hash(d.head)
    o = d.write(0, [ch("obj|Threshold|t1", value=3)])
    assert o.kind == "conflict" and o.conflicts == [("obj|Threshold|t1", "value")] and d.head == 1 and d.hash(d.head) == h


def test_same_value_on_both_sides_and_distinct_properties_of_one_object_are_compatible():
    d = M.Dag(BASE)
    d.write(0, [ch("obj|Component|c1", path="q")])
    assert d.write(0, [ch("obj|Component|c1", path="q")]).kind == "ok"
    assert d.write(0, [ch("obj|Component|c1", orphan_flagged=True)]).kind == "ok"
    assert d.state(d.head)["obj|Component|c1"] == {"id": "c1", "path": "q", "orphan_flagged": True}


def test_never_mode_refuses_every_stale_write_and_a_fresh_write_still_passes():
    d = M.Dag(BASE)
    d.write(0, [ch("obj|Threshold|t1", value=2)], "never")
    assert d.write(0, [ch("obj|Component|c1", path="q")], "never").kind == "conflict"
    assert d.write(d.head, [ch("obj|Component|c1", path="q")], "never").kind == "ok"


def test_rejections_missing_endpoint_and_immutable_pin():
    d = M.Dag({**BASE, "obj|Evidence|e1": {"id": "e1", "git_commit": "A", "payload_hash": "h", "experiment_version": "1", "environment": "x"}})
    assert d.write(0, [ch("lnk|EXISTS_FOR|Component|zz|Hypothesis|h1")]).kind == "rejected"
    o = d.write(0, [ch("obj|Evidence|e1", git_commit="B")])
    assert o.kind == "rejected" and "immutable" in o.problems[0] and d.head == 0


def test_a_created_object_carries_its_key_as_id_property():
    d = M.Dag(BASE)
    d.write(0, [ch("obj|Metric|m9", name="n")])
    assert d.state(1)["obj|Metric|m9"] == {"id": "m9", "name": "n"}


def test_oracle_is_independent_static_known_positive_and_known_negative(tmp_path):
    assert oracle_imports()["independent"] and oracle_imports()["files"]
    for bad in ("import eoo_engine\n", "from eoo_engine_git import GitStore\n", "from domains.project import pack\n", "import subprocess\n", "x = open('f')\n"):
        f = tmp_path / "bad_oracle.py"
        f.write_text(bad)
        r = oracle_imports([f])
        assert not r["independent"] and r["forbidden"], bad


def test_model_does_not_mutate_its_inputs():
    b = copy.deepcopy(BASE)
    M.apply_change(b, [ch("obj|Threshold|t1", value=9)])
    M.three_way(b, {**b, "obj|Threshold|t1": {"id": "t1", "value": 9}}, b)
    assert b == BASE
