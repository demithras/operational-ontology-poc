"""Codegen freshness, strict models, and the policy engine against the shared static reference."""
import pytest

from conventional import codegen
from conventional.models_gen import OPERATION_MODELS
from conventional.policy import PolicyEngine
from conventional.validation import RequestInvalid
from r3_shared.authspec import allowed_operations, load_auth_spec
from r3_shared.opsspec import DOMAINS, load_ops_spec


def test_generated_models_are_up_to_date():
    assert codegen.main(["--check"]) == 0


def test_a_stale_generated_file_is_detected(tmp_path, monkeypatch):
    stale = tmp_path / "models_gen.py"
    stale.write_text("# stale\n")
    monkeypatch.setattr(codegen, "OUT", stale)
    assert codegen.main(["--check"]) == 1


def test_one_model_per_operation_with_resource_types_from_spec():
    for d in DOMAINS:
        for op in load_ops_spec(d)["operations"]:
            m = OPERATION_MODELS[op["name"]]
            assert m.DOMAIN == d and m.GATED == tuple(op["gated_inputs"])
            assert {n: t for n, t in m.RESOURCES.items()} == {i["name"]: i["resource_type"] for i in op["inputs"] if i["type"] == "resource"}


@pytest.mark.parametrize("args,reason", [
    ({}, "missing_field"), ({"claim": 5}, "bad_type"), ({"claim": None}, "missing_field"), ({"claim": "x", "extra": 1}, "unknown_field"),
    ({"claim": "x", "principal": "admin-1"}, "unknown_field"),
])
def test_models_reject_bad_input(args, reason):
    with pytest.raises(RequestInvalid) as e:
        OPERATION_MODELS["create_hypothesis"].from_args(args)
    assert e.value.reason == reason


def test_models_reject_bool_as_integer_and_non_dict():
    M = OPERATION_MODELS["expedite_purchase_order"]
    for bad in ({"po_id": "P", "expedite_fee": True}, {"po_id": "P", "expedite_fee": 1.0}, {"po_id": " ", "expedite_fee": 1}, [1]):
        with pytest.raises(RequestInvalid):
            M.from_args(bad)
    assert M.from_args({"po_id": "P", "expedite_fee": 0}).inputs() == {"po_id": "P", "expedite_fee": 0}


@pytest.mark.parametrize("domain", DOMAINS)
def test_policy_static_exposure_matches_shared_reference_for_non_delegated(domain):
    spec, ops = load_auth_spec(domain), [o["name"] for o in load_ops_spec(domain)["operations"]]
    eng = PolicyEngine(spec)
    for p in spec["principals"]:
        if True:
            assert set(eng.exposed_operations(p["id"], ops)) == allowed_operations(spec, p["id"], ops), p["id"]


def test_policy_orphan_agent_is_a_delegate_of_nobody_and_denied():
    """P1b: delegated_by is intrinsic; agent-orphan is evaluated as the delegate of nobody-1 on every request."""
    spec = load_auth_spec("manufacturing")
    eng = PolicyEngine(spec)
    assert not eng.decide("agent-orphan", None, "transfer_inventory", [("Warehouse", "WH-A")]).allowed
    assert not eng.decide("agent-orphan", "nobody-1", "transfer_inventory", [("Warehouse", "WH-A")]).allowed
    assert not eng.decide("agent-1", "senior-1", "transfer_inventory", [("Warehouse", "WH-A")]).allowed
    assert not eng.decide("planner-1", "agent-1", "transfer_inventory", [("Warehouse", "WH-A")]).allowed  # null delegator
    assert allowed_operations(spec, "agent-orphan", ["transfer_inventory"]) == set()


def test_policy_deny_overrides_allow_and_unknown_principals_are_denied():
    spec = load_auth_spec("manufacturing")
    spec["grants"].append({"delegable": False, "effect": "deny", "id": "x", "operation": "transfer_inventory",
                           "principal": {"id": "planner-1"}, "resource": {"any": True}})
    eng = PolicyEngine(spec)
    assert not eng.decide("planner-1", None, "transfer_inventory", [("Warehouse", "WH-A")]).allowed
    assert eng.decide("admin-1", None, "transfer_inventory", [("Warehouse", "WH-A")]).allowed
    assert not eng.decide("ghost", None, "transfer_inventory", []).allowed
    assert not eng.decide("agent-1", "planner-1", "transfer_inventory", [("Warehouse", "WH-A")]).allowed  # deny on delegator


def test_policy_relation_must_hold_on_every_input_resource():
    eng = PolicyEngine(load_auth_spec("manufacturing"))
    assert eng.decide("agent-hostile-1", "planner-1", "transfer_inventory", [("Warehouse", "WH-B"), ("Warehouse", "WH-C")]).allowed
    assert not eng.decide("agent-hostile-1", "planner-1", "transfer_inventory", [("Warehouse", "WH-B"), ("Warehouse", "WH-A")]).allowed
    assert not eng.decide("planner-1", None, "transfer_inventory", []).allowed  # relation selector needs >= 1 such input


def test_approver_must_be_independent_of_requester_chain():
    eng = PolicyEngine(load_auth_spec("manufacturing"))
    W = [("Warehouse", "WH-A")]
    assert eng.can_approve("senior-1", "agent-1", "planner-1", "approval:large_transfer", W)
    assert not eng.can_approve("admin-1", "admin-1", None, "approval:large_transfer", W)       # self
    assert not eng.can_approve("planner-1", "agent-1", "planner-1", "approval:large_transfer", W)  # delegator
    assert not eng.can_approve("junior-1", "planner-1", None, "approval:large_transfer", W)    # no approval grant
