"""P2a rework: delegate semantics (PROT-H23), outcome mapping with reasons, protocol-level mutants/approval surface."""
import pytest

from paladin.variant import PaladinVariant

TR = {"source_warehouse": "WH-A", "destination_warehouse": "WH-B", "part": "PX-17", "quantity": 5}


def zero(rig, fn):
    res, eff = rig.effects_of(fn)
    assert eff == [], f"unexpected world effects {eff} (result {res})"
    return res


@pytest.mark.parametrize("src,dst", [("WH-A", "WH-B"), ("WH-A", "WH-C"), ("WH-B", "WH-C")])
@pytest.mark.parametrize("via", ["direct", "tool"])
def test_orphan_delegate_is_denied_everywhere(mfg, src, dst, via):
    f = mfg.dep.direct if via == "direct" else mfg.dep.call_tool
    part = "PX-17" if src == "WH-A" else "PX-900"
    res = zero(mfg, lambda: f(mfg.token("agent-orphan"), "transfer_inventory",
                              {**TR, "source_warehouse": src, "destination_warehouse": dst, "part": part}, request_id=mfg.rid()))
    assert res.status == "DENIED" and isinstance(res.body["reason"], str) and res.body["reason"]


def test_delegate_without_on_behalf_of_is_evaluated_as_delegate(mfg):
    res, eff = mfg.effects_of(lambda: mfg.dep.direct(mfg.token("agent-1"), "transfer_inventory", TR, request_id="a1"))
    assert res.status == "OK" and len(eff) == 1


def test_wrong_or_stray_on_behalf_of_is_denied(mfg):
    for who, obo in (("agent-1", "senior-1"), ("agent-1", "nobody-1"), ("planner-1", "planner-1"), ("nobody-1", "planner-1")):
        res = zero(mfg, lambda: mfg.dep.direct(mfg.token(who), "transfer_inventory", TR, on_behalf_of=obo, request_id=mfg.rid()))
        assert res.status == "DENIED" and res.body["reason"], (who, obo)


def test_delegate_tools_are_its_delegation_surface_without_on_behalf_of(mfg):
    assert [d.name for d in mfg.dep.tools(mfg.token("agent-1"))] == ["transfer_inventory"]
    assert mfg.dep.tools(mfg.token("agent-orphan")) == []


def test_every_negative_carries_status_and_reason(mfg, proj):
    TRC = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
    cases = [  # (rig, call, expected status)
        (mfg, lambda: mfg.dep.direct(mfg.token("agent-hostile-1"), "transfer_inventory", {**TRC, "source_warehouse": "WH-A"}, request_id="n1"), "DENIED"),
        (mfg, lambda: mfg.dep.direct(mfg.token("nobody-1"), "reschedule_work_order", {"work_order_id": "WO-43", "new_planned_start": 55}, request_id="n2"), "DENIED"),
        (mfg, lambda: mfg.dep.direct("garbage", "transfer_inventory", TRC, request_id="n3"), "DENIED"),
        (mfg, lambda: mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", {**TRC, "principal": "admin-1"}, request_id="n4"), "INVALID"),
        (mfg, lambda: mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", {**TRC, "quantity": "x"}, request_id="n5"), "INVALID"),
        (mfg, lambda: mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", {**TRC, "quantity": 9999}, request_id="n6"), None),
        (mfg, lambda: mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory", {**TRC, "quantity": 400}, request_id="n7"), "DENIED"),
        (mfg, lambda: mfg.dep.direct(mfg.token("planner-1"), "nope", {}, request_id="n8"), "UNKNOWN"),
        (proj, lambda: proj.dep.direct(proj.token("researcher-1"), "create_hypothesis", {"claim": "ephemeral: x"}, request_id="n9"), "DENIED"),
        (proj, lambda: proj.dep.direct(proj.token("viewer-1"), "create_hypothesis", {"claim": "x"}, request_id="n10"), "DENIED"),
        (proj, lambda: proj.dep.direct(proj.token("researcher-1"), "start_run", {"hypothesis": "H-A"}, request_id="n11"), "DENIED"),
    ]
    for rig, call, status in cases:
        res = zero(rig, call)
        assert res.status != "OK" and (status is None or res.status == status), (res, status)
        assert isinstance(res.body.get("reason"), str) and res.body["reason"].strip(), res


def test_replay_after_revoke_has_reason(mfg):
    import copy
    t = mfg.token("planner-1")
    assert mfg.dep.direct(t, "transfer_inventory", TR, request_id="r1").status == "OK"
    revoked = copy.deepcopy(mfg.auth)
    revoked["grants"] = [g for g in revoked["grants"] if g["id"] != "transfer-inventory-planner"]
    mfg.dep.set_authority(revoked)
    res = zero(mfg, lambda: mfg.dep.direct(t, "transfer_inventory", TR, request_id="r1"))
    assert res.status == "DENIED" and res.body["reason"]


def test_approve_surface(mfg):
    big = {**TR, "quantity": 400}
    r = mfg.dep.approve("garbage", "transfer_inventory", big, "planner-1")
    assert r.status == "DENIED" and r.body["reason"]
    r = mfg.dep.approve(mfg.token("senior-1"), "transfer_inventory", big, "ghost")
    assert r.status == "DENIED" and r.body["reason"]
    r = mfg.dep.approve(mfg.token("senior-1"), "transfer_inventory", {**big, "principal": "x"}, "planner-1")
    assert r.status == "INVALID" and r.body["reason"]


def test_load_variant_with_mutants():
    from r3_shared.registry import load_variant
    assert isinstance(load_variant("paladin", mutants=["tool_overexposure"]), PaladinVariant)
