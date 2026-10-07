"""E-9: the exact schema-INVALID set decides whether a decision gets an envelope (hand-written expectations)."""
import pytest

from conv_g2_util import TRANSFER, edge, make_g2

PO = {"po_id": "PO-991", "expedite_fee": 1}


@pytest.fixture
def rig(tmp_path):
    r = make_g2(tmp_path, with_history=True)
    yield r
    r.close()


def envs(r):
    return len(r.history.keys("env/"))


def bad_edge(**kw):
    e = edge("e-x", "planner-1", "nobody-1")
    for k, v in kw.items():
        if v is KeyError:
            del e[k]
        else:
            e[k] = v
    return e


DELEGATE = [  # (edge, envelope?)
    (edge("g1", "planner-1", "nobody-1"), True),
    (edge("g2", "planner-1", "nobody-1", ops=("not_an_op",)), True),  # semantic refusals stay governed
    (bad_edge(id=""), False), (bad_edge(id=5), False), (bad_edge(id=KeyError), False),
    (bad_edge(issuer=None), False), (bad_edge(child=""), False), (bad_edge(parent=3), False),
    (bad_edge(redelegable="yes"), False), (bad_edge(issued_at=True), False), (bad_edge(issued_at=1.5), False),
    (bad_edge(expires_at="soon"), False), (bad_edge(scope=None), False), (bad_edge(scope={"operations": []}), False),
    (bad_edge(extra=1), False), ("not-a-dict", False), (None, False), ([], False),
]


@pytest.mark.parametrize("e,env", DELEGATE)
def test_delegate_envelope_iff_edge_schema_valid(rig, e, env):
    n = envs(rig)
    rig.dep.delegate(rig.token("planner-1"), e, "r-d")
    assert (envs(rig) - n) == (1 if env else 0)


REVOKE = [("nope", True), ("", False), ("   ", False), (None, False), (5, False), (["e1"], False), ({"id": "e1"}, False)]


@pytest.mark.parametrize("eid,env", REVOKE)
def test_revoke_envelope_iff_edge_id_non_empty_string(rig, eid, env):
    n = envs(rig)
    rig.dep.revoke(rig.token("planner-1"), eid, "r-r")
    assert (envs(rig) - n) == (1 if env else 0)


CALLS = [  # (operation, args, envelope?)
    ("transfer_inventory", TRANSFER, True),
    ("transfer_inventory", {**TRANSFER, "extra": 1}, False),
    ("transfer_inventory", {k: v for k, v in TRANSFER.items() if k != "part"}, False),
    ("transfer_inventory", {**TRANSFER, "part": None}, False),
    ("transfer_inventory", {**TRANSFER, "quantity": "10"}, False),
    ("transfer_inventory", {**TRANSFER, "quantity": True}, False),
    ("transfer_inventory", {**TRANSFER, "part": " "}, False),
    ("transfer_inventory", {**TRANSFER, "part": 7}, False),
    ("transfer_inventory", {**TRANSFER, "part": "NO-SUCH-PART"}, True),  # existence is governed, not schema
    ("transfer_inventory", [], False), ("transfer_inventory", None, False),
    ("no_such_op", {}, False),
    ("expedite_purchase_order", PO, True),
    ("expedite_purchase_order", {**PO, "expedite_fee": "1"}, False),
    ("expedite_purchase_order", {**PO, "expedite_fee": False}, False),
]


@pytest.mark.parametrize("kind", ["call_tool", "direct"])
@pytest.mark.parametrize("op,args,env", CALLS)
def test_call_envelope_iff_schema_valid(rig, kind, op, args, env):
    n = envs(rig)
    getattr(rig.dep, kind)(rig.token("planner-1"), op, args, None, "r-c")
    assert (envs(rig) - n) == (1 if env else 0)


@pytest.mark.parametrize("op,args,env", CALLS)
def test_approve_envelope_iff_approved_request_schema_valid(rig, op, args, env):
    n = envs(rig)
    rig.dep.approve(rig.token("planner-1"), op, args, "junior-1", None)
    assert (envs(rig) - n) == (1 if env else 0)
