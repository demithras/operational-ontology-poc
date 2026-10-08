"""G3 fix4: G3-E23 list_links on an unknown link type answers OK {"out": [], "in": []} (the oracle low-view form)."""
import pytest

from conv_g3_util import diff, make_g3

PL = "planner-1"
EMPTY = {"out": [], "in": []}


@pytest.fixture
def r(tmp_path):
    return make_g3(tmp_path, "hierarchical", governance=None, sub="")


@pytest.mark.parametrize("ref", ["WorkOrder:WO-42", "PurchaseOrder:PO-991", "Part:none", "nonsense"])
def test_unknown_link_type_answers_ok_empty_without_world_effects(r, ref):
    before, head = r.snap(), len(r.reader.log())
    res = r.dep.list_links(r.token(PL), ref, "No_such_link_type")
    assert (res.status, res.body) == ("OK", EMPTY)
    assert diff(before, r.snap()) == [] and len(r.reader.log()) == head


def test_known_link_type_still_answers_links(r):
    res = r.dep.list_links(r.token(PL), "WorkOrder:WO-42", "WorkOrder_warehouse")
    assert res.status == "OK" and res.body["out"] == ["Warehouse:WH-A"]
