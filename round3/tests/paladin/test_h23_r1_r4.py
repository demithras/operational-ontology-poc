"""H23 requirements R1-R4: every negative asserts ZERO world-store effects (measured by snapshot diff)."""
import copy

import pytest

from paladin_rig import Rig  # noqa: F401

TR = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
BIG = {**TR, "quantity": 400}


def zero(rig, fn):
    res, eff = rig.effects_of(fn)
    assert eff == [], f"unexpected world effects {eff} (result {res})"
    return res


# ---- R1 identity binding ------------------------------------------------------------------------------------
@pytest.mark.parametrize("field", ["principal", "actor", "owner", "requested_by", "sub", "on_behalf_of", "user"])
@pytest.mark.parametrize("via", ["direct", "tool"])
def test_r1_identity_fields_in_args_never_select_authority(mfg, field, via):
    t = mfg.token("agent-hostile-1")
    args = {**TR, field: "planner-1"}
    f = mfg.dep.direct if via == "direct" else mfg.dep.call_tool
    res = zero(mfg, lambda: f(t, "transfer_inventory", args, request_id=mfg.rid()))
    assert res.status == "INVALID"


def test_r1_bad_tokens_denied_with_zero_effects(mfg):
    good = mfg.token("planner-1")
    forged = good[:-4] + ("0000" if not good.endswith("0000") else "1111")
    short = mfg.token("planner-1", ttl=5)
    mfg.clock.advance(10)
    for bad in (forged, mfg.token("planner-1", aud="someone-else"), short, "", "a.b", None):
        for f in (mfg.dep.direct, mfg.dep.call_tool):
            res = zero(mfg, lambda: f(bad, "transfer_inventory", TR, request_id=mfg.rid()))
            assert res.status == "DENIED"
    assert mfg.dep.tools(forged) == [] and mfg.dep.tools(short) == []


def test_r1_unknown_principal_with_valid_token_denied(mfg):
    res = zero(mfg, lambda: mfg.dep.direct(mfg.token("ghost-9"), "transfer_inventory", TR, request_id="r1"))
    assert res.status == "DENIED"


def test_r1_token_subject_cannot_claim_other_delegator(mfg):
    # agent-orphan is delegated by nobody-1 who holds nothing; delegating to planner-1 is not in its delegation table
    res = zero(mfg, lambda: mfg.dep.direct(mfg.token("agent-orphan"), "transfer_inventory", TR, on_behalf_of="planner-1",
                                           request_id="r1"))
    assert res.status == "DENIED"
    res = zero(mfg, lambda: mfg.dep.direct(mfg.token("agent-orphan"), "transfer_inventory", TR, on_behalf_of="nobody-1",
                                           request_id="r2"))
    assert res.status == "DENIED"  # delegator itself holds no grant: (c) fails


def test_r1_delegation_requires_listed_operation_and_delegable_grant(mfg, proj):
    # agent-1 may act for planner-1 only for transfer_inventory
    res = zero(mfg, lambda: mfg.dep.direct(mfg.token("agent-1"), "expedite_purchase_order",
                                           {"po_id": "PO-992", "expedite_fee": 10}, on_behalf_of="planner-1", request_id="r1"))
    assert res.status == "DENIED"
    # project: no delegations at all
    res = zero(proj, lambda: proj.dep.direct(proj.token("agent-evidence-1"), "start_run", {"hypothesis": "H-B"},
                                             on_behalf_of="researcher-1", request_id="r1"))
    assert res.status == "DENIED"


# ---- R2 server-side backstop ---------------------------------------------------------------------------------
MFG_CALLS = [("transfer_inventory", TR), ("expedite_purchase_order", {"po_id": "PO-992", "expedite_fee": 10}),
             ("reschedule_work_order", {"work_order_id": "WO-43", "new_planned_start": 55})]


@pytest.mark.parametrize("who", ["nobody-1", "agent-hostile-1", "agent-orphan"])
@pytest.mark.parametrize("op,args", MFG_CALLS[1:])
def test_r2_direct_denies_what_the_tool_surface_hides(mfg, who, op, args):
    t = mfg.token(who)
    assert op not in [d.name for d in mfg.dep.tools(t)]
    assert zero(mfg, lambda: mfg.dep.direct(t, op, args, request_id="r1")).status == "DENIED"
    assert zero(mfg, lambda: mfg.dep.call_tool(t, op, args, request_id="r2")).status == "UNKNOWN"


def test_r2_direct_denies_out_of_scope_resource_for_visible_tool(mfg):
    t = mfg.token("agent-hostile-1")  # holds agent_grant on WH-B/WH-C only; WH-A destination is out of scope
    args = {**TR, "destination_warehouse": "WH-A"}
    for f in (mfg.dep.direct, mfg.dep.call_tool):
        assert zero(mfg, lambda: f(t, "transfer_inventory", args, on_behalf_of="planner-1", request_id=mfg.rid())).status == "DENIED"


def test_r2_project_viewer_and_agents(proj):
    for who, op, args in (("viewer-1", "create_hypothesis", {"claim": "x"}), ("agent-evidence-1", "create_hypothesis", {"claim": "y"}),
                          ("agent-draft-1", "start_run", {"hypothesis": "H-B"}), ("researcher-1", "delete_everything", {})):
        res = zero(proj, lambda: proj.dep.direct(proj.token(who), op, args, request_id=proj.rid()))
        assert res.status in ("DENIED", "UNKNOWN")


# ---- R3 least exposure ---------------------------------------------------------------------------------------
def test_r3_tools_are_subset_of_static_authority(mfg, proj):
    from r3_shared.authspec import allowed_operations
    for rig in (mfg, proj):
        ops = [o["name"] for o in rig.ops["operations"]]
        as_itself = copy.deepcopy(rig.auth)  # PROT-H23: without on_behalf_of the subject is evaluated as itself
        for p in as_itself["principals"]:
            p["delegated_by"] = None
        for p in rig.auth["principals"]:
            listed = {d.name for d in rig.dep.tools(rig.token(p["id"]))}
            bound = set(allowed_operations(as_itself, p["id"], ops))
            for d in rig.auth["delegations"]:  # operations reachable by delegation
                if d["agent"] == p["id"]:
                    bound |= set(allowed_operations(as_itself, d["on_behalf_of"], ops)) & set(d["operations"])
            assert listed <= bound, (p["id"], listed - bound)
    assert [d.name for d in proj.dep.tools(proj.token("viewer-1"))] == []
    assert {d.name for d in proj.dep.tools(proj.token("agent-evidence-1"))} == {"start_run", "attach_evidence"}


def test_r3_hidden_tool_guessing_has_no_effect(mfg):
    t = mfg.token("nobody-1")
    for guess in ("expedite_purchase_order", "transfer_inventory", "write_canonical_state", "../x", "", None, 7):
        assert zero(mfg, lambda: mfg.dep.call_tool(t, guess, TR, request_id=mfg.rid())).status in ("UNKNOWN", "DENIED")


# ---- R4 decision binding -------------------------------------------------------------------------------------
def test_r4_pending_request_is_bound_to_its_inputs(mfg):
    t = mfg.token("planner-1")
    res = zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", BIG, request_id="r9"))
    assert res.body["state"] == "PENDING_APPROVAL"
    held = copy.deepcopy(res.body)
    res.body["quantity"] = 1  # the caller scribbles on what it was handed; this is a copy, not execution state
    res.body.setdefault("inputs", {})["quantity"] = 1
    # same request id, changed gated input -> refused, never mutates the pending decision
    again = zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", {**BIG, "quantity": 300}, request_id="r9"))
    assert again.status == "INVALID"
    other_part = zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", {**BIG, "part": "PX-17"}, request_id="r9"))
    assert other_part.status == "INVALID"
    res2, eff = mfg.effects_of(lambda: mfg.dep.approve(mfg.token("senior-1"), "r9"))
    assert res2.status == "OK" and len(eff) == 1 and eff[0]["payload"]["quantity"] == 400 and held["state"] == "PENDING_APPROVAL"


def test_r4_returned_records_are_copies(proj):
    res = proj.dep.read(proj.token("viewer-1"), "get", {"type": "Hypothesis", "key": "H-A"})
    res.body["value"]["props"]["phase"] = "EVALUATED"
    before = proj.snap()
    assert proj.dep.read(proj.token("viewer-1"), "get", {"type": "Hypothesis", "key": "H-A"}).body["value"]["props"]["phase"] == "DRAFT"
    assert proj.snap() == before


def test_r4_inputs_are_copied_at_the_boundary(mfg):
    args = dict(TR)
    t = mfg.token("planner-1")
    res, eff = mfg.effects_of(lambda: mfg.dep.direct(t, "transfer_inventory", args, request_id="r1"))
    args["quantity"] = 61  # mutate the held dict after the call: nothing may change retroactively
    assert eff[0]["payload"]["quantity"] == 60 and res.status == "OK"
