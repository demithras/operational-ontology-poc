"""G5 fix1 (errata G5-E10..E14): hand-written from the frozen errata text."""
import hashlib

import pytest

from conv_g5_util import DEP, EXPEDITE, TRANSFER, make_g5, stop_all
from r3_shared.extadapter import canon_json
from r3_shared.recovery import INPUT_INVALID_REASONS, validate_reply, validate_recovery_view

BAD_TOKENS = ("not-a-token", "")
EDGE = {"id": "E-x", "issuer": "planner-1", "child": "planner-2", "parent": None, "expires_at": None, "redelegable": False,
        "issued_at": 1, "scope": {"operations": ["transfer_inventory"], "resources": []}}


@pytest.fixture
def rig(tmp_path):
    r = make_g5(tmp_path / "r", ext=True)
    yield r
    stop_all()


def unav(node):
    return ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": node})


def bad_calls(rig):
    d = rig.dep
    out = []
    for t in BAD_TOKENS:
        out += [("execute", d.direct(t, "transfer_inventory", TRANSFER, None, "rb1")),
                ("call_tool", d.call_tool(t, "transfer_inventory", TRANSFER, None, "rb2")),
                ("approve", d.approve(t, "expedite_purchase_order", EXPEDITE, "planner-1")),
                ("revoke", d.revoke(t, "E-1", "rb3")),
                ("delegate", d.delegate(t, EDGE, "rb4"))]
    return out


# -- G5-E13 ---------------------------------------------------------------------------------------------------------------
def test_invalid_token_while_auth_down_is_unavailable_auth_never_denied(rig):
    rig.actl.outage(DEP, 2, 9)
    for kind, r in bad_calls(rig):
        assert (r.status, r.body) == unav("AUTH"), kind
        validate_reply(r.status, r.body)
    r = rig.dep.read("not-a-token", "get", {"type": "Warehouse", "key": "WH-A"})
    assert (r.status, r.body) == unav("AUTH")


def test_invalid_token_while_anchor_down_is_unavailable_anchor_for_mutations(rig):
    assert rig.d("planner-1", "transfer_inventory", TRANSFER, "r0").status == "OK"
    rig.actl_anchor.partition(rig.dep.service.stream, 3, 9, "drop")
    rig.tick()
    for kind, r in bad_calls(rig):
        assert (r.status, r.body) == unav("ANCHOR"), kind


def test_expired_token_while_auth_down_is_unavailable(rig):
    t = rig.token("planner-1", ttl=1)
    rig.tick(3)
    rig.actl.outage(DEP, 5, 20)
    rig.tick()
    r = rig.dep.direct(t, "transfer_inventory", TRANSFER, None, "re1")
    assert (r.status, r.body) == unav("AUTH")


def test_deps_up_legacy_denied_unchanged(rig):
    for kind, r in bad_calls(rig):
        assert r.status in ("DENIED", "INVALID"), kind
        assert "dependency" not in r.body, kind
    r = rig.dep.direct("not-a-token", "transfer_inventory", TRANSFER, None, "ru1")
    assert (r.status, r.body["reason"]) == ("DENIED", "invalid_token")


# -- G5-E11 ---------------------------------------------------------------------------------------------------------------
def test_approvals_open_is_the_canonical_fingerprint_with_non_ascii_args(rig):
    args = {"po_id": "PO-пример-ü", "expedite_fee": 900}
    r = rig.dep.approve(rig.token("supervisor-1"), "expedite_purchase_order", args, "planner-1")
    assert r.status == "OK", (r.status, r.body)
    view = rig.dep.service.recovery_view()
    validate_recovery_view(view)
    exp = hashlib.sha256(canon_json({"subject": "planner-1", "on_behalf_of": None, "operation": "expedite_purchase_order",
                                     "inputs": args}).encode()).hexdigest()
    assert view["approvals_open"] == [exp]


# -- G5-E12 / E10 / E14 -----------------------------------------------------------------------------------------------------
import sqlite3  # noqa: E402

from r3_shared.host import HostDead  # noqa: E402


def ext_rows(rig):
    con = sqlite3.connect(f"file:{rig.tmp / 'ext' / 'external.db'}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM effects").fetchone()[0]
    finally:
        con.close()


def cp2_kill(rig, rid, op="expedite_purchase_order", args=EXPEDITE, sub="planner-1"):
    px = rig.host()
    px.advance(rig.clock.now())
    px.arm("CP2_after_commit", rid)
    with pytest.raises(HostDead):
        px.direct(rig.token(sub), op, args, None, rid)
    px.wait_dead()


@pytest.fixture
def hrig(tmp_path):
    r = make_g5(tmp_path / "h", ext=True, deploy=False)
    yield r
    stop_all()


def test_cp2_crash_before_heal_in_doubt_after_heal_original_decision_no_new_rows(hrig):
    rig = hrig
    cp2_kill(rig, "r1")
    assert rig.commits() == ["r1"]
    stream = rig.hist.get("meta/stream").decode()
    rig.actl_anchor.partition(stream, 2, 8, "drop")           # ANCHOR down until the heal
    px = rig.host(resume=True)
    px.advance(rig.clock.now())
    pre = px.direct(rig.token("planner-1"), "expedite_purchase_order", EXPEDITE, None, "r1")
    assert (pre.status, pre.body.get("reason")) in (("UNKNOWN", "in_doubt"), ("UNAVAILABLE", "dependency_unavailable"))
    if pre.status == "UNAVAILABLE":
        assert pre.body["dependency"] == "ANCHOR"
    assert rig.commits() == ["r1"]
    rig.tick(6)                                               # tick 8: healed
    px.advance(rig.clock.now())
    assert px.dispatch_pending().status == "OK"
    rig.tick(4)
    px.advance(rig.clock.now())
    px.reconcile("r1", rig.clock.now())
    world_before, ext_before = len(rig.reader.log()), ext_rows(rig)
    again = px.direct(rig.token("planner-1"), "expedite_purchase_order", EXPEDITE, None, "r1")
    assert again.status == "OK" and again.body["replayed"] is True
    assert len(rig.reader.log()) == world_before and ext_rows(rig) == ext_before == 1
    assert rig.anchor.lookup(stream, "r1") is not None
    assert px.replay("r1").status == "VERIFIED"
    v = validate_recovery_view(px.recovery_view())
    assert [i["state"] for i in v["intents"]] == ["RECONCILED_SUCCESS"]


def test_commit_without_request_id_is_anchored_on_first_governed_call_after_resume(rig):
    svc = rig.dep.service
    inner = rig.anchor

    class Lose:
        def __getattr__(self, n):
            return getattr(inner, n)

        def append(self, *a):
            from r3_shared.anchor import AnchorUnavailable
            raise AnchorUnavailable("injected")

    svc.anchor = svc.prov.anchor = Lose()
    rig.fresh()
    r = rig.dep.direct(rig.token("planner-1"), "transfer_inventory", TRANSFER, None, None)
    assert r.status == "UNKNOWN" and rig.anchor.head(svc.stream) is None
    head_before = 0
    rig.restart()
    assert rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 1}, "r2").status == "OK"
    assert rig.anchor.head(svc.stream)["seq"] == head_before + 2      # the rid-less commit AND r2 are anchored
    rig.restart()                                                       # a second resume re-finishes the journal: no duplicate
    assert rig.d("planner-1", "transfer_inventory", {**TRANSFER, "quantity": 2}, "r3").status == "OK"
    assert rig.anchor.head(svc.stream)["seq"] == head_before + 3
    assert rig.dep.replay("r2").status == "VERIFIED"


def test_view_authority_version_is_the_leased_digest_not_delegation_state(rig):
    from r3_shared.authsvc import doc_digest
    assert rig.d("planner-1", "transfer_inventory", TRANSFER, "r1").status == "OK"
    c = validate_recovery_view(rig.dep.recovery_view())["committed"]
    from conv_g5_util import V0
    assert c[0]["authority_version"] == doc_digest(V0)
    assert c[0]["authority_version"] == rig.dep.recovery_view()["authority"]["version"]


def test_invalid_while_blocked_uses_input_invalid_reasons_verbatim(rig):
    rig.actl.outage(DEP, 2, 9)
    shapes = [("no_such_op", {}), ("transfer_inventory", {"part": 1}), ("transfer_inventory", dict(TRANSFER, quantity=1.5))]
    for i, (op, a) in enumerate(shapes):
        r = rig.d("planner-1", op, a, f"x{i}", fresh=False)
        assert r.status == "INVALID" and r.body["reason"] in INPUT_INVALID_REASONS, (op, r.body)
    r = rig.dep.delegate(rig.token("planner-1"), {"bad": 1}, "d1")
    assert r.status == "INVALID" and r.body["reason"] in INPUT_INVALID_REASONS
    r = rig.dep.delegate(rig.token("planner-1"), EDGE, "")
    assert r.status == "INVALID" and r.body["reason"] in INPUT_INVALID_REASONS

