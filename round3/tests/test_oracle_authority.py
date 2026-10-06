import copy

import pytest

from r3_oracle import authority
from r3_shared.authspec import load_auth_spec

M = load_auth_spec("manufacturing")
P = load_auth_spec("project")
WH = lambda a, b: [("Warehouse", a), ("Warehouse", b), ("Part", "PX-17")]  # noqa: E731
OP = "transfer_inventory"


def d(subject, obo, op, res, spec=M):
    return authority.decide(subject, obo, op, res, spec).allow


def test_planner_allowed_junior_allowed_nobody_denied():
    assert d("planner-1", None, OP, WH("WH-A", "WH-B"))
    assert d("junior-1", None, OP, WH("WH-A", "WH-B"))
    assert not d("nobody-1", None, OP, WH("WH-A", "WH-B"))
    assert not d("ghost-9", None, OP, WH("WH-A", "WH-B"))


def test_relation_must_hold_on_every_input_resource_of_the_type():
    assert d("agent-hostile-1", None, OP, WH("WH-B", "WH-C"))
    assert not d("agent-hostile-1", None, OP, WH("WH-A", "WH-C"))  # WH-A not held: EVERY input must be held
    assert not d("agent-hostile-1", None, OP, [("Part", "PX-17")])  # at least one resource of the type must exist


def test_on_behalf_of_requires_delegation_delegable_grant_and_delegator_allowed():
    assert d("agent-1", "planner-1", OP, WH("WH-A", "WH-B"))
    assert not d("agent-1", "junior-1", OP, WH("WH-A", "WH-B"))  # no delegation entry for junior-1
    assert not d("agent-1", "planner-1", "expedite_purchase_order", [("PurchaseOrder", "PO-991")])  # op not delegated
    assert not d("agent-orphan", "nobody-1", OP, WH("WH-A", "WH-B"))  # delegator allowed nothing
    assert not d("agent-hostile-1", "planner-1", OP, WH("WH-A", "WH-C"))  # agent itself not allowed there


def test_non_delegable_grant_blocks_delegation():
    spec = copy.deepcopy(M)
    for g in spec["grants"]:
        if g["id"] == "transfer-inventory-agent-grant":
            g["delegable"] = False
    assert d("agent-1", None, OP, WH("WH-A", "WH-B"), spec)
    assert not d("agent-1", "planner-1", OP, WH("WH-A", "WH-B"), spec)


def test_deny_overrides_allow_and_delegation_chain_deny():
    spec = copy.deepcopy(M)
    spec["grants"].append({"id": "x", "effect": "deny", "operation": OP, "principal": {"id": "planner-1"},
                           "resource": {"any": True}, "delegable": False, "origin": "test"})
    assert not d("planner-1", None, OP, WH("WH-A", "WH-B"), spec)
    assert not d("agent-1", "planner-1", OP, WH("WH-A", "WH-B"), spec)
    spec2 = copy.deepcopy(M)
    spec2["grants"].append({"id": "y", "effect": "deny", "operation": "*", "principal": {"role": "planner"},
                            "resource": {"any": True}, "delegable": False, "origin": "test"})
    assert d("admin-1", None, OP, WH("WH-A", "WH-B"), spec2)  # admin holds role admin only: the planner deny misses it
    assert not d("planner-1", None, "reschedule_work_order", [("WorkOrder", "WO-43")], spec2)


def test_pseudo_operation_deny_does_not_match_real_operations():
    assert d("planner-1", None, "reschedule_work_order", [("WorkOrder", "WO-43")])


def test_project_roles_and_no_delegation():
    assert d("researcher-1", None, "start_run", [("Hypothesis", "H-B")], P)
    assert not d("viewer-1", None, "start_run", [("Hypothesis", "H-B")], P)
    assert d("agent-evidence-1", None, "attach_evidence", [], P)
    assert not d("agent-evidence-1", None, "evaluate_hypothesis", [], P)
    assert not d("agent-evidence-1", "researcher-1", "start_run", [], P)  # delegations empty


def test_admin_star_and_approver_rule():
    assert d("admin-1", None, "approval:large_transfer", [("Warehouse", "WH-A")])
    assert authority.approver_ok("planner-1", "senior-1", M)
    assert not authority.approver_ok("planner-1", "planner-1", M)
    assert not authority.approver_ok("agent-1", "planner-1", M)  # delegator is inside the delegation chain


def test_could_ever_allow_is_an_upper_bound_of_decide():
    assert authority.could_ever_allow("agent-hostile-1", OP, M)
    assert not authority.could_ever_allow("agent-hostile-1", "expedite_purchase_order", M)
    assert not authority.could_ever_allow("viewer-1", "start_run", P)
    assert authority.could_ever_allow("admin-1", "start_run", P)


def test_revoke_removes_grants_and_delegations():
    new = authority.revoke(M, "planner-1", OP)
    assert not d("planner-1", None, OP, WH("WH-A", "WH-B"), new)
    assert d("junior-1", None, OP, WH("WH-A", "WH-B"), new)  # others unaffected
    new2 = authority.revoke(M, "agent-1", OP)
    assert not d("agent-1", "planner-1", OP, WH("WH-A", "WH-B"), new2)
    assert M["delegations"], "revoke must copy, not mutate"
