"""PROT-H24 requirements R24-1..R24-4 (conventional). Hand-written expectations from the frozen text: world-diff and
world_log based, no oracle. Each requirement has a positive and a negative (refusal with zero change)."""
import pytest

from conv_g2_util import PART, TRANSFER, WH, edge, make_g2, v2_spec
from r3_shared.world import diff

PLANNER, NOBODY, JUNIOR, SUPER = "planner-1", "nobody-1", "junior-1", "supervisor-1"


@pytest.fixture
def rig(tmp_path):
    r = make_g2(tmp_path)
    yield r
    r.close()


def chain(r, n=2):
    """planner-1 -e1-> nobody-1 -e2-> junior-1 -e3-> supervisor-1 (each delegation by the previous child)."""
    who = [PLANNER, NOBODY, JUNIOR, SUPER]
    for i in range(n):
        res = r.dep.delegate(r.token(who[i]), edge(f"e{i + 1}", who[i], who[i + 1], f"e{i}" if i else None), f"d{i}")
        assert res.status == "OK", res


def authority_unchanged(r, before_version, before_marks):
    assert r.dep.authority_version() == before_version
    assert len(r.marks("authority")) == before_marks


# ---- R24-1 attenuation ------------------------------------------------------------------------------------------
def test_r24_1_amplified_scope_is_refused_with_zero_change(rig):
    chain(rig, 1)
    v, m = rig.dep.authority_version(), len(rig.marks("authority"))
    wider = edge("bad", NOBODY, JUNIOR, "e1", ops=("transfer_inventory", "expedite_purchase_order"))
    r = rig.dep.delegate(rig.token(NOBODY), wider, "bad1")
    assert (r.status, r.body["reason"]) == ("DENIED", "scope_amplification")
    keys = edge("bad2", NOBODY, JUNIOR, "e1", res=({"type": "Warehouse", "keys": None}, {"type": "Part", "keys": None},
                                                  {"type": "WorkOrder", "keys": None}))
    assert rig.dep.delegate(rig.token(NOBODY), keys, "bad2").body["reason"] == "scope_amplification"
    authority_unchanged(rig, v, m)


def test_r24_1_expiry_amplification_and_root_without_delegable_grant(rig):
    rig.dep.delegate(rig.token(PLANNER), edge("e1", PLANNER, NOBODY, expires=50), "d0")
    for exp in (None, 51):
        r = rig.dep.delegate(rig.token(NOBODY), edge(f"x{exp}", NOBODY, JUNIOR, "e1", expires=exp), f"r{exp}")
        assert (r.status, r.body["reason"]) == ("DENIED", "expiry_amplification")
    # root edge for an operation no delegable grant covers
    r = rig.dep.delegate(rig.token(PLANNER), edge("root2", PLANNER, JUNIOR, ops=("expedite_purchase_order",)), "r2")
    assert (r.status, r.body["reason"]) == ("DENIED", "scope_amplification")
    ok = rig.dep.delegate(rig.token(NOBODY), edge("ok", NOBODY, JUNIOR, "e1", expires=40), "okk")
    assert ok.status == "OK"


def test_r24_1_effect_commits_only_inside_the_intersection_of_every_scope(rig):
    narrow = (WH, PART)
    rig.dep.delegate(rig.token(PLANNER), edge("e1", PLANNER, NOBODY, res=narrow), "d0")
    only_b = ({"type": "Warehouse", "keys": ["WH-B"]}, PART)  # child scope excludes the destination WH-A
    assert rig.dep.delegate(rig.token(NOBODY), edge("e2", NOBODY, JUNIOR, "e1", res=only_b), "d1").status == "OK"
    before = rig.snap()
    r = rig.dep.direct(rig.token(JUNIOR), "transfer_inventory", TRANSFER, PLANNER, "x1")  # touches WH-A and WH-B
    assert (r.status, r.body["reason"]) == ("DENIED", "no_valid_path")
    assert diff(before, rig.snap()) == []
    # the parent edge alone (holder nobody-1) does cover both warehouses: the intersection is what refused junior
    assert rig.dep.direct(rig.token(NOBODY), "transfer_inventory", TRANSFER, PLANNER, "x2").status == "OK"


# ---- R24-2 freshness --------------------------------------------------------------------------------------------
def test_r24_2_revoked_edge_cannot_commit_and_the_downstream_chain_dies_with_it(rig):
    chain(rig, 3)
    assert rig.dep.direct(rig.token(SUPER), "transfer_inventory", TRANSFER, PLANNER, "a").status == "OK"
    assert rig.dep.revoke(rig.token(NOBODY), "e2", "rv").status == "OK"  # an upstream holder cuts downstream
    before = rig.snap()
    r = rig.dep.direct(rig.token(SUPER), "transfer_inventory", {**TRANSFER, "quantity": 3}, PLANNER, "b")
    assert (r.status, r.body["reason"]) == ("DENIED", "no_valid_path")
    assert diff(before, rig.snap()) == []
    # e1 (upstream of the cut) is still alive
    assert rig.dep.direct(rig.token(NOBODY), "transfer_inventory", {**TRANSFER, "quantity": 2}, PLANNER, "c").status == "OK"


def test_r24_2_expiry_is_strict_usable_at_tick_9_not_at_tick_10(tmp_path):
    r = make_g2(tmp_path, start=3)
    try:
        assert r.dep.delegate(r.token(PLANNER), edge("e1", PLANNER, NOBODY, expires=10), "d0").status == "OK"
        r.clock.advance(6)  # tick 9
        h = r.store.handle("seed")
        h.update("EvidenceSnapshot", "ES-1", {"snapshotObservedAt": 9})  # keep the business-rule evidence fresh
        h.close()
        assert r.dep.direct(r.token(NOBODY), "transfer_inventory", TRANSFER, PLANNER, "t9").status == "OK"
        r.clock.advance(1)  # tick 10
        before = r.snap()
        res = r.dep.direct(r.token(NOBODY), "transfer_inventory", {**TRANSFER, "quantity": 2}, PLANNER, "t10")
        assert (res.status, res.body["reason"]) == ("DENIED", "no_valid_path")
        assert diff(before, r.snap()) == []
        late = r.dep.delegate(r.token(PLANNER), edge("e2", PLANNER, JUNIOR, expires=10), "d1")  # already expired
        assert (late.status, late.body["reason"]) == ("INVALID", "already_expired")
    finally:
        r.close()


def test_r24_2_root_losing_base_authority_kills_every_path_rooted_at_it(rig):
    chain(rig, 2)
    spec = v2_spec(extra_edges=rig.dep.authority_state()["capabilities"])
    for p in spec["principals"]:
        if p["id"] == PLANNER:
            p["relations"] = [x for x in p["relations"] if x["relation"] != "planner"]
    rig.dep.set_authority(spec)
    before = rig.snap()
    r = rig.dep.direct(rig.token(JUNIOR), "transfer_inventory", TRANSFER, PLANNER, "x")
    assert (r.status, r.body["reason"]) == ("DENIED", "no_valid_path") and diff(before, rig.snap()) == []


# ---- R24-3 linearizable boundary --------------------------------------------------------------------------------
def test_r24_3_revoke_then_execute_and_execute_then_revoke_follow_the_log_order(rig):
    chain(rig, 1)
    a = rig.dep.direct(rig.token(NOBODY), "transfer_inventory", TRANSFER, PLANNER, "first")  # returns before the revoke
    rv = rig.dep.revoke(rig.token(PLANNER), "e1", "rv")
    b = rig.dep.direct(rig.token(NOBODY), "transfer_inventory", {**TRANSFER, "quantity": 2}, PLANNER, "second")
    assert (a.status, rv.status, b.status) == ("OK", "OK", "DENIED")
    seq = {m["data"].get("request_id"): m["seq"] for m in rig.marks("commit")}
    revoke_authority = next(m["seq"] for m in rig.marks("authority") if m["data"]["op"] == "revoke")
    assert seq["first"] < revoke_authority < seq["rv"]  # the authority mark is in the same transaction as its commit mark
    assert "second" not in seq  # a refused request writes nothing: no commit point


def test_r24_3_revoke_is_durable_before_ok_and_marked(rig):
    chain(rig, 1)
    n = len(rig.marks("authority"))
    assert rig.dep.revoke(rig.token(PLANNER), "e1", "rv").status == "OK"
    new = rig.marks("authority")[n:]
    assert len(new) == 1 and new[0]["data"]["op"] == "revoke" and new[0]["data"]["edge_id"] == "e1"
    assert new[0]["data"]["version"] == rig.dep.authority_version()  # same transaction as the revocation
    again = rig.dep.revoke(rig.token(PLANNER), "e1", "rv2")  # already revoked: OK, no new authority mark
    assert again.status == "OK" and again.body == {"already": True} and len(rig.marks("authority")) == n + 1


# ---- R24-4 explicit conflict ------------------------------------------------------------------------------------
@pytest.mark.parametrize("who,e,reason,status", [
    (NOBODY, edge("c1", NOBODY, PLANNER, "e1"), "delegation_cycle", "INVALID"),            # child is the root issuer
    (NOBODY, edge("c2", NOBODY, NOBODY, "e1"), "delegation_cycle", "INVALID"),            # issuer == child
    (NOBODY, edge("c3", NOBODY, JUNIOR, "nope"), "unknown_parent", "INVALID"),
    (JUNIOR, edge("c4", JUNIOR, SUPER, "e1"), "not_parent_holder", "DENIED"),             # junior does not hold e1
    (NOBODY, edge("c5", NOBODY, "agent-1"), "static_delegate", "INVALID"),                 # H23 static delegates: disjoint
    (NOBODY, edge("c6", NOBODY, "ghost-9", "e1"), "unknown_principal", "INVALID"),
    (NOBODY, edge("e1", NOBODY, JUNIOR, "e1"), "duplicate_edge", "INVALID"),
    (NOBODY, {"id": "c7"}, "schema", "INVALID"),
])
def test_r24_4_conflicts_fail_with_the_named_reason_and_zero_change(rig, who, e, reason, status):
    chain(rig, 1)
    v, m, before = rig.dep.authority_version(), len(rig.marks("authority")), rig.snap()
    r = rig.dep.delegate(rig.token(who), e, "req")
    assert (r.status, r.body["reason"]) == (status, reason), r
    authority_unchanged(rig, v, m)
    assert diff(before, rig.snap()) == []


def test_r24_4_depth_overflow_and_bad_token_and_wrong_obo(tmp_path):
    spec = v2_spec()
    spec["max_delegation_depth"] = 2
    r = make_g2(tmp_path, spec=spec)
    try:
        chain(r, 2)
        r3 = r.dep.delegate(r.token(JUNIOR), edge("e3", JUNIOR, SUPER, "e2"), "d3")
        assert (r3.status, r3.body["reason"]) == ("INVALID", "depth_exceeded")
        assert r.dep.delegate("garbage", edge("z", PLANNER, JUNIOR), "z").body["reason"] == "token"
        # wrong on_behalf_of: nobody-1 holds an edge rooted at planner-1, not at senior-1: no fallback to base authority
        before = r.snap()
        w = r.dep.direct(r.token(NOBODY), "transfer_inventory", TRANSFER, "senior-1", "w")
        assert (w.status, w.body["reason"]) == ("DENIED", "no_valid_path") and diff(before, r.snap()) == []
        # an edge holder with NO on_behalf_of gets only its own base authority (none): edges never apply
        n = r.dep.direct(r.token(NOBODY), "transfer_inventory", TRANSFER, None, "n")
        assert n.status == "DENIED" and diff(before, r.snap()) == []
    finally:
        r.close()
