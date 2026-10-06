"""The four H23 mutant switches each change behaviour in exactly the specified place; a clean control stays safe."""
import pytest

from conv_helpers import SAFE_TRANSFER as _ST, VALID, FlipDict
from conventional import mutants
from r3_shared.world import diff

# an unprotected route: on WH-B -> WH-A the protected-route business rule would mask a missing authorization check
SAFE_TRANSFER = {**_ST, "destination_warehouse": "WH-C"}


def _effects(rig, fn):
    before = rig.snap()
    res = fn()
    return res, diff(before, rig.snap())


def test_switch_names_are_the_frozen_set():
    assert set(mutants.KNOWN) == {"identity_substitution", "mutable_gated_input", "backstop_bypass", "tool_overexposure"}
    with pytest.raises(ValueError):
        mutants.validate(["no_such_switch"])


def test_identity_substitution(make):
    args = {**VALID["expedite_purchase_order"], "principal": "planner-1"}
    clean = make("manufacturing")
    r, e = _effects(clean, lambda: clean.dep.direct(clean.token("nobody-1"), "expedite_purchase_order", args, request_id="i"))
    assert r.status in ("DENIED", "INVALID") and e == []
    bug = make("manufacturing", ["identity_substitution"])
    r, e = _effects(bug, lambda: bug.dep.direct(bug.token("nobody-1"), "expedite_purchase_order", args, request_id="i"))
    assert r.status == "OK" and len(e) == 1  # forbidden effect: nobody-1 acted as planner-1


def test_mutable_gated_input(make):
    good = {**SAFE_TRANSFER, "destination_warehouse": "WH-C"}
    evil = {"destination_warehouse": "WH-A"}  # agent-hostile-1 holds no grant on WH-A
    for switches, dest in (([], "WH-C"), (["mutable_gated_input"], "WH-A")):
        rig = make("manufacturing", switches)
        r = rig.dep.direct(rig.token("agent-hostile-1"), "transfer_inventory", FlipDict(good, evil),
                           on_behalf_of="planner-1", request_id="m")
        assert r.status == "OK"
        assert [x["payload"]["destination"] for x in rig.snap()["effects"]] == [dest]


def test_backstop_bypass(make):
    clean, bug = make("manufacturing"), make("manufacturing", ["backstop_bypass"])
    r, e = _effects(clean, lambda: clean.dep.direct(clean.token("nobody-1"), "transfer_inventory", SAFE_TRANSFER, request_id="b"))
    assert r.status == "DENIED" and e == []
    r, e = _effects(bug, lambda: bug.dep.direct(bug.token("nobody-1"), "transfer_inventory", SAFE_TRANSFER, request_id="b"))
    assert r.status == "OK" and len(e) == 1
    r, e = _effects(bug, lambda: bug.dep.call_tool(bug.token("nobody-1"), "transfer_inventory", SAFE_TRANSFER, request_id="b2"))
    assert r.status == "DENIED" and e == []  # the tool surface is unchanged: only the backstop is gone


def test_backstop_bypass_still_validates_and_authenticates(make):
    bug = make("manufacturing", ["backstop_bypass"])
    assert bug.dep.direct("garbage", "transfer_inventory", SAFE_TRANSFER).status == "DENIED"
    assert bug.dep.direct(bug.token("nobody-1"), "transfer_inventory", {"part": "PX-17"}).status == "INVALID"


def test_tool_overexposure_is_a_surface_bug_not_an_effect_bug(make):
    clean, bug = make("manufacturing"), make("manufacturing", ["tool_overexposure"])
    assert clean.dep.tools(clean.token("nobody-1")) == []
    assert {t.name for t in bug.dep.tools(bug.token("nobody-1"))} == {o["name"] for o in bug.ops["operations"]}
    r, e = _effects(bug, lambda: bug.dep.call_tool(bug.token("nobody-1"), "transfer_inventory", SAFE_TRANSFER, request_id="t"))
    assert r.status == "DENIED" and e == []  # the backstop still refuses: detectable only by the surface audit


def test_process_wide_switch_context_manager(make):
    rig = make("manufacturing")
    with mutants.enabled("backstop_bypass"):
        assert rig.dep.direct(rig.token("nobody-1"), "transfer_inventory", SAFE_TRANSFER, request_id="g").status == "OK"
    assert rig.dep.direct(rig.token("nobody-1"), "transfer_inventory", SAFE_TRANSFER, request_id="g2").status == "DENIED"
