"""E-9 (Paladin): the envelope decision is exactly the complement of the schema-INVALID set. One table per kind:
(case, expect_envelope). Envelope count is read from the HistoryStore, never from a return value."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g2_hist import envelopes  # noqa: E402
from g2_rig import TR, G2Rig, edge, new_anchor  # noqa: E402
from test_pal_g2_project import mk  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")
BIG = {**TR, "quantity": 400}


@pytest.fixture(scope="module")
def anchor(tmp_path_factory):
    ap = new_anchor(tmp_path_factory.mktemp("anchor"))
    yield ap
    ap.close()


def n_env(r):
    return len(envelopes(r))


def without(d, k):
    return {a: b for a, b in d.items() if a != k}


# (case id, operation, args, expect envelope) - requester planner-1 (authorized for transfer_inventory); ag-9-style
# unauthorized cases use the same table through ACTORS below.
OPS_CASES = [
    ("valid", "transfer_inventory", TR, True),
    ("valid_optional_absent", "transfer_inventory", TR, True),
    ("valid_optional_set", "transfer_inventory", {**TR, "work_order": "WO-1"}, True),
    ("valid_nonexistent_object", "transfer_inventory", {**TR, "part": "NO-SUCH-PART"}, True),  # E-6: existence is governed
    ("unknown_key", "transfer_inventory", {**TR, "extra": 1}, False),
    ("identity_like_key", "transfer_inventory", {**TR, "principal": "x"}, False),
    ("missing_required", "transfer_inventory", without(TR, "part"), False),
    ("null_required", "transfer_inventory", {**TR, "part": None}, False),
    ("null_optional_is_absent", "transfer_inventory", {**TR, "work_order": None}, True),
    ("int_as_string", "transfer_inventory", {**TR, "quantity": "60"}, False),
    ("int_as_float", "transfer_inventory", {**TR, "quantity": 60.0}, False),
    ("int_as_bool", "transfer_inventory", {**TR, "quantity": True}, False),
    ("resource_as_int", "transfer_inventory", {**TR, "part": 7}, False),
    ("resource_blank", "transfer_inventory", {**TR, "part": ""}, False),
    ("resource_whitespace", "transfer_inventory", {**TR, "part": "  "}, False),
    ("args_not_object", "transfer_inventory", [TR], False),
    ("unknown_op", "no_such_operation", TR, False),
]
PROJ_CASES = [
    ("json_object", "edit_threshold", {"threshold": "no-such", "value": {"a": 1}}, True),
    ("json_number", "edit_threshold", {"threshold": "no-such", "value": 0.5}, True),
    ("json_bool", "edit_threshold", {"threshold": "no-such", "value": False}, True),
    ("json_null_required", "edit_threshold", {"threshold": "no-such", "value": None}, False),
    ("json_missing", "edit_threshold", {"threshold": "no-such"}, False),
    ("proj_unknown_key", "edit_threshold", {"threshold": "no-such", "value": 1, "x": 1}, False),
]


def run_direct(r, who, op, args):
    return r.dep.direct(r.token(who), op, args, request_id=r.rid())


def run_tool(r, who, op, args):
    return r.dep.call_tool(r.token(who), op, args, request_id=r.rid())


@pytest.mark.parametrize("who", ["planner-1", "ag-1"])  # authorized / unauthorized: schema decides first either way
@pytest.mark.parametrize("via", [run_direct, run_tool])
@pytest.mark.parametrize("case,op,args,expect", OPS_CASES, ids=[c[0] for c in OPS_CASES])
def test_e9_call_kinds(tmp_path, anchor, case, op, args, expect, via, who):
    r = G2Rig(tmp_path, history=True, anchor=anchor.client())
    before, snap = n_env(r), r.snap()
    via(r, who, op, copy.deepcopy(args))
    assert (n_env(r) - before == 1) == expect, (case, via.__name__, who)
    assert n_env(r) - before in (0, 1)
    if not expect:
        assert r.snap() == snap  # zero world effects


@pytest.mark.parametrize("via", [run_direct, run_tool])
@pytest.mark.parametrize("case,op,args,expect", PROJ_CASES, ids=[c[0] for c in PROJ_CASES])
def test_e9_json_type(tmp_path, anchor, case, op, args, expect, via):
    r = mk(tmp_path, history=True, anchor=anchor.client())
    before = n_env(r)
    via(r, "researcher-1", op, args)
    assert (n_env(r) - before == 1) == expect, case


APPROVE_CASES = [
    ("valid", "transfer_inventory", BIG, True),
    ("unknown_key", "transfer_inventory", {**BIG, "extra": 1}, False),
    ("missing_required", "transfer_inventory", without(BIG, "part"), False),
    ("null_required", "transfer_inventory", {**BIG, "quantity": None}, False),
    ("int_as_string", "transfer_inventory", {**BIG, "quantity": "400"}, False),
    ("int_as_bool", "transfer_inventory", {**BIG, "quantity": True}, False),
    ("resource_blank", "transfer_inventory", {**BIG, "part": ""}, False),
    ("args_not_object", "transfer_inventory", "x", False),
    ("unknown_op", "no_such_operation", BIG, False),
]


@pytest.mark.parametrize("approver", ["senior-1", "ag-1"])  # capable / not capable: both governed when the schema is valid
@pytest.mark.parametrize("case,op,args,expect", APPROVE_CASES, ids=[c[0] for c in APPROVE_CASES])
def test_e9_approve(tmp_path, anchor, case, op, args, expect, approver):
    r = G2Rig(tmp_path, history=True, anchor=anchor.client())
    before = n_env(r)
    r.dep.approve(r.token(approver), op, args, "planner-1")
    assert (n_env(r) - before == 1) == expect, case


def good():
    return edge("e1", "planner-1", "ag-1")


def mut(**kw):
    return {**good(), **kw}


DELEGATE_CASES = [
    ("valid", good(), True),
    ("semantic_unknown_parent", mut(parent="nope"), True),
    ("semantic_cycle", edge("e1", "planner-1", "planner-1"), True),
    ("semantic_unknown_child", mut(child="ghost"), True),
    ("empty_issuer_is_schema_valid", mut(issuer=""), True),
    ("empty_child_is_schema_valid", mut(child=""), True),
    ("empty_parent_is_schema_valid", mut(parent=""), True),
    ("extra_key", {**good(), "x": 1}, False),
    ("missing_key", without(good(), "scope"), False),
    ("empty_id", mut(id=""), False),
    ("id_int", mut(id=3), False),
    ("issuer_int", mut(issuer=3), False),
    ("expires_bool", mut(expires_at=True), False),
    ("expires_float", mut(expires_at=1.5), False),
    ("issued_null", mut(issued_at=None), False),
    ("redelegable_int", mut(redelegable=1), False),
    ("scope_not_dict", mut(scope=[]), False),
    ("scope_extra", mut(scope={"operations": [], "resources": [], "x": 1}), False),
    ("ops_not_list", mut(scope={"operations": "a", "resources": []}), False),
    ("ops_item_int", mut(scope={"operations": [1], "resources": []}), False),
    ("res_item_not_dict", mut(scope={"operations": [], "resources": ["Warehouse"]}), False),
    ("res_keys_missing", mut(scope={"operations": [], "resources": [{"type": "Warehouse"}]}), False),
    ("res_extra", mut(scope={"operations": [], "resources": [{"type": "W", "keys": None, "x": 1}]}), False),
    ("res_key_int", mut(scope={"operations": [], "resources": [{"type": "W", "keys": [1]}]}), False),
    ("edge_not_object", "e1", False),
    ("edge_none", None, False),
]


@pytest.mark.parametrize("who", ["planner-1", "ag-2"])
@pytest.mark.parametrize("case,e,expect", DELEGATE_CASES, ids=[c[0] for c in DELEGATE_CASES])
def test_e9_delegate(tmp_path, anchor, case, e, expect, who):
    r = G2Rig(tmp_path, history=True, anchor=anchor.client())
    before = n_env(r)
    r.delegate(who, copy.deepcopy(e))
    assert (n_env(r) - before == 1) == expect, case


REVOKE_CASES = [("known_edge", "e1", True), ("unknown_edge", "zzz", True), ("empty", "", False), ("int", 3, False),
                ("none", None, False), ("list", ["e1"], False), ("whitespace_is_nonempty_string", " ", True)]


@pytest.mark.parametrize("who", ["planner-1", "ag-2"])
@pytest.mark.parametrize("case,eid,expect", REVOKE_CASES, ids=[c[0] for c in REVOKE_CASES])
def test_e9_revoke(tmp_path, anchor, case, eid, expect, who):
    r = G2Rig(tmp_path, history=True, anchor=anchor.client())
    assert r.delegate("planner-1", good(), "setup").status == "OK"
    before = n_env(r)
    r.revoke(who, eid)
    assert (n_env(r) - before == 1) == expect, case
