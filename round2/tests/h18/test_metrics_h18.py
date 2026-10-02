"""Bespoke-surface measurement: counting rules, disjoint complete attribution, TC3 actually implemented in both variants."""
import json
import textwrap

from eoo_exp.util import ROOT
from eoo_h18 import loc, manifest, metrics


def test_python_code_lines_skip_blank_comment_and_docstring(tmp_path):
    f = tmp_path / "m.py"
    f.write_text(textwrap.dedent('''\
        """module doc
        two lines"""
        import os   # comment

        # only a comment
        def f(x):
            """doc"""
            return (x +
                    1)
    '''))
    assert sorted(loc.code_lines(f)) == [3, 6, 8, 9]


def test_json_is_counted_in_one_normalised_form():
    assert loc.json_lines({"a": [1, 2], "b": {"c": 1}}) == len(json.dumps({"a": [1, 2], "b": {"c": 1}}, indent=2).splitlines()) == 9


def test_every_python_line_of_every_listed_file_is_assigned_and_classes_are_disjoint():
    m = metrics.measure({c: {"eoo": True, "baseline": True} for c in metrics.CLASSES})
    assert m["python_unassigned_lines"] == {"eoo": {}, "baseline": {}}
    total = sum(sum(v.values()) for v in m["assignment"]["eoo"]["python"].values())
    assert total == sum(len(loc.code_lines(ROOT / f)) for f in {x["py"] for x in manifest.eoo() if "py" in x})


def test_each_class_total_is_the_sum_of_its_assignment_and_all_three_classes_are_measured():
    m = metrics.measure({c: {"eoo": True, "baseline": True} for c in metrics.CLASSES})
    for c in metrics.CLASSES:
        e = m["per_class"][c]
        assert e["eoo"]["total"] == e["eoo"]["python_loc"] + e["eoo"]["config_lines"] + e["eoo"]["mandatory_extras"]["total"]
        assert e["baseline"]["total"] > 0 and e["eoo"]["total"] > 0
    assert m["recurring_complexity_loc"]["eoo"] > 0 and m["recurring_complexity_loc"]["baseline"] > 0
    assert {"EXCL:freeze_hash_computation", "EXCL:h19_git_authority"} <= set(m["excluded_not_counted"])


def test_a_listed_symbol_that_does_not_exist_fails_loudly():
    import pytest
    with pytest.raises(KeyError):
        loc.assign([{"cls": "X", "py": "src/eoo_h18/loc.py", "sym": "no_such_symbol"}])


def test_tc3_is_implemented_in_both_variants():
    ir = json.loads((ROOT / "src/eoo_h18/tc_patch.json").read_text())
    assert {"Replication"} == {o["id"] for o in ir["object_types"]} and "REPLICATES" in {l["id"] for l in ir["link_types"]}
    assert {a["id"] for a in ir["actions"]} == {"register_replication"} and "count_replications" in {f["id"] for f in ir["functions"]}
    from baselines.h18_fileonly import replication
    assert callable(replication.register) and callable(replication.count) and callable(replication.violations)
    assert (ROOT / "baselines/h18_fileonly/schemas/replication.schema.json").exists()
