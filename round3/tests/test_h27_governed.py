"""E-8: the oracle (ops-spec input schema / authority well-formedness) decides governed-ness, never variant reason text."""
import copy

import pytest

from r3_harness.h27.stream import is_governed, oracle_schema_invalid
from r3_oracle import ops_model

from r3_shared.authspec import load_auth_spec
from r3_shared.opsspec import load_ops_spec

OPS = load_ops_spec("manufacturing")
AUTH = load_auth_spec("manufacturing")
SNAP = {"objects": {f"{o['type']}:{o['key']}": {"props": dict(o["props"]), "version": 1} for o in OPS["seed"]["objects"]},
        "links": [[x["link_type"], x["src"], x["dst"]] for x in OPS["seed"]["links"]], "effects": []}
GOOD = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 10}
EDGE = {"id": "e1", "issuer": "p", "child": "c", "parent": None, "scope": {"operations": ["transfer_inventory"], "resources": []},
        "expires_at": None, "redelegable": False, "issued_at": 0}


@pytest.mark.parametrize("bad", [{**GOOD, "quantity": "ten"}, {k: v for k, v in GOOD.items() if k != "quantity"},
                                 {**GOOD, "part": ""}, "not-an-object"])
def test_schema_invalid_requests_and_approvals_are_outside_the_governed_set(bad):
    for kind in ("call_tool", "direct", "approve"):
        if kind == "approve":
            assert oracle_schema_invalid(OPS, kind, "transfer_inventory", bad)
    assert oracle_schema_invalid(OPS, "approve", "no_such_op", GOOD)


def test_valid_args_are_governed_whatever_the_variants_status_or_reason():
    assert not oracle_schema_invalid(OPS, "approve", "transfer_inventory", GOOD)
    out = ops_model.evaluate(OPS, AUTH, "planner-1", None, "transfer_inventory", {**GOOD, "destination_warehouse": "NOPE"},
                             SNAP, 1)
    assert out.kind != ops_model.COMMIT and is_governed(out)  # DENIED/INVALID after the schema gate: governed
    ok = ops_model.evaluate(OPS, AUTH, "planner-1", None, "transfer_inventory", GOOD, SNAP, 1)
    assert ok.kind == ops_model.COMMIT and is_governed(ok)


def test_schema_invalid_request_outcome_is_not_governed():
    out = ops_model.evaluate(OPS, AUTH, "planner-1", None, "transfer_inventory", {**GOOD, "quantity": "ten"}, SNAP, 1)
    assert out.kind == ops_model.INVALID and not is_governed(out)
    pre = ops_model.evaluate(OPS, AUTH, "planner-1", None, "transfer_inventory", {**GOOD, "quantity": 0}, SNAP, 1)
    assert pre.kind == ops_model.INVALID and is_governed(pre)  # precondition INVALID is governed


def test_delegate_and_revoke_schema_is_decided_by_the_oracle():
    assert not oracle_schema_invalid(OPS, "delegate", None, EDGE)
    broken = copy.deepcopy(EDGE)
    del broken["scope"]
    assert oracle_schema_invalid(OPS, "delegate", None, broken) and oracle_schema_invalid(OPS, "delegate", None, "x")
    assert not oracle_schema_invalid(OPS, "revoke", None, "e1")
    assert oracle_schema_invalid(OPS, "revoke", None, "") and oracle_schema_invalid(OPS, "revoke", None, 3)
