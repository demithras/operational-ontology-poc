"""H24 (Paladin): one test per requirement R24-1..R24-7, each with a negative; expectations are hand-written and measured from
the world store (world_log marks/ticks, snapshot diffs), never from return values alone."""
import threading
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g2_rig import G2Rig, TR, edge, v2_mfg  # noqa: E402

ALL_WH = [{"type": "Warehouse", "keys": None}, {"type": "Part", "keys": None}, {"type": "WorkOrder", "keys": None}]


@pytest.fixture
def rig(tmp_path):
    return G2Rig(tmp_path)


def head(r):
    return r.snap()["log_head"]


def zero_change(r, h):
    """No world row at all (no effect, no authority mark) since log head `h`."""
    return r.log(h) == []


def marks(r, after=0, kind=None):
    return [x for x in r.log(after) if x["kind"] == "mark" and (kind is None or x["ref"] == kind)]


# ---- R24-1 attenuation ------------------------------------------------------------------------------------------------
def test_r24_1_attenuation_refused_and_zero_change(rig):
    WB = [{"type": "Warehouse", "keys": ["WH-B", "WH-C"]}, {"type": "Part", "keys": None}]
    assert rig.delegate("planner-1", edge("p", "planner-1", "ag-1", resources=WB, expires=50)).status == "OK"
    h = head(rig)
    wide = [("scope_amplification", dict(ops=["transfer_inventory", "expedite_purchase_order"])),
            ("scope_amplification", dict(resources=[{"type": "Warehouse", "keys": None}, {"type": "Part", "keys": None}])),
            ("scope_amplification", dict(resources=[{"type": "Warehouse", "keys": ["WH-A"]}, {"type": "Part", "keys": None}])),
            ("scope_amplification", dict(resources=WB + [{"type": "WorkOrder", "keys": None}])),
            ("expiry_amplification", dict(expires=51)), ("expiry_amplification", dict(expires=None))]
    for i, (why, kw) in enumerate(wide):
        res = rig.delegate("ag-1", edge(f"c{i}", "ag-1", "ag-2", "p", **{**dict(resources=WB, expires=50), **kw}))
        assert (res.status, res.body["reason"]) == ("DENIED", why), (i, res)
    assert zero_change(rig, h)
    # root edge: the issuer must hold a delegable grant for every op in scope
    assert rig.delegate("nobody-1", edge("r", "nobody-1", "ag-3")).body["reason"] == "scope_amplification"
    assert rig.delegate("planner-1", edge("r2", "planner-1", "ag-3", ops=["transfer_inventory", "reschedule_work_order"])).status == "DENIED"
    assert zero_change(rig, h)
    # legal attenuations commit with an authority mark; use is bounded by the INTERSECTION of every scope on the path
    assert rig.delegate("ag-1", edge("c", "ag-1", "ag-2", "p", resources=WB, expires=40)).status == "OK"
    narrow = [{"type": "Warehouse", "keys": ["WH-C"]}, {"type": "Part", "keys": None}]
    assert rig.delegate("ag-1", edge("n", "ag-1", "ag-3", "p", resources=narrow, expires=40)).status == "OK"
    assert len(marks(rig, h, "authority")) == 2
    _, eff = rig.effects_of(lambda: rig.transfer("ag-2", "planner-1"))
    assert len(eff) == 1
    h = head(rig)
    assert rig.transfer("ag-3", "planner-1").status == "DENIED" and zero_change(rig, h)  # TR touches WH-B: outside the child's scope
    assert rig.transfer("ag-1", "planner-1").status == "OK"  # the parent alone may


# ---- R24-2 freshness at the commit point -------------------------------------------------------------------------------
def test_r24_2_revoked_expired_and_root_authority_loss(rig):
    for i, ag in enumerate(("ag-1", "ag-2", "ag-3")):
        assert rig.delegate("planner-1", edge(f"e{i}", "planner-1", ag, expires=5 if i == 2 else None)).status == "OK"
    assert rig.delegate("ag-1", edge("e1d", "ag-1", "ag-4", "e0")).status == "OK"
    assert rig.transfer("ag-4", "planner-1").status == "OK"
    assert rig.revoke("planner-1", "e0").status == "OK"  # revoking the parent invalidates the whole subtree
    h = head(rig)
    for sub in ("ag-1", "ag-4"):
        assert rig.transfer(sub, "planner-1").body == {"reason": "no_valid_path"}  # G3: refusal bodies carry only the reason (PROT-H26 3.6)
    assert zero_change(rig, h)
    # expiry boundary: usable at tick 4, not at tick 5 (strict; the evidence rule keeps ticks small)
    rig.clock.advance(4)
    assert rig.transfer("ag-3", "planner-1").status == "OK"
    rig.clock.advance(1)
    h = head(rig)
    assert rig.transfer("ag-3", "planner-1").status == "DENIED" and zero_change(rig, h)
    # root loses base authority: set_authority removing the planner grant kills every path rooted there
    assert rig.transfer("ag-2", "planner-1").status == "OK"
    weaker = v2_mfg()
    weaker["grants"] = [g for g in weaker["grants"] if g["id"] not in ("transfer-inventory-planner", "g24-planner-transfer")]
    weaker["capabilities"] = rig.dep.authority_state()["capabilities"]
    weaker["revoked"] = ["e0"]
    rig.dep.set_authority(weaker)
    h = head(rig)
    assert rig.transfer("ag-2", "planner-1").status == "DENIED" and zero_change(rig, h)
    assert [m["data"]["op"] for m in marks(rig, 0, "authority")][-1] == "set_authority"


def test_r24_2_retry_semantics_after_revocation(rig):
    assert rig.delegate("planner-1", edge("e", "planner-1", "ag-1")).status == "OK"
    assert rig.transfer("ag-1", "planner-1", rid="same").status == "OK"
    assert rig.revoke("planner-1", "e").status == "OK"
    res, eff = rig.effects_of(lambda: rig.transfer("ag-1", "planner-1", rid="same"))  # stored result, never a second effect
    assert res.status == "OK" and res.body.get("replayed") is True and eff == []
    res, eff = rig.effects_of(lambda: rig.transfer("ag-1", "planner-1", rid="fresh"))  # new id: decided against current authority
    assert res.status == "DENIED" and eff == []


# ---- R24-3 linearizable boundary ---------------------------------------------------------------------------------------
def test_r24_3_commit_order_matches_real_time_and_races_have_one_legitimate_outcome(tmp_path):
    for n in range(12):
        (tmp_path / f"r{n}").mkdir()
        r = G2Rig(tmp_path / f"r{n}")
        assert r.delegate("planner-1", edge("e", "planner-1", "ag-1")).status == "OK"
        out, bar = {}, threading.Barrier(2)

        def do_rev():
            bar.wait()
            out["rev"] = r.revoke("planner-1", "e")

        def do_req():
            bar.wait()
            out["req"] = r.transfer("ag-1", "planner-1", rid="race")
        ts = [threading.Thread(target=f) for f in (do_rev, do_req)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert out["rev"].status == "OK"
        log = r.log()
        rev_seq = next(m["seq"] for m in log if m["kind"] == "mark" and m["ref"] == "authority" and m["data"].get("op") == "revoke")
        eff_seq = [m["seq"] for m in log if m["kind"] == "mark" and m["ref"] == "commit" and m["data"]["request_id"] == "race"]
        assert (out["req"].status == "OK") == bool(eff_seq) and (not eff_seq or eff_seq[0] < rev_seq)  # effect only BEFORE the revoke
    # real-time precedence (sequential control): X returned before Y was invoked -> seq(X) < seq(Y), both orders
    (tmp_path / "seq").mkdir()
    r = G2Rig(tmp_path / "seq")
    assert r.delegate("planner-1", edge("e", "planner-1", "ag-1")).status == "OK"
    assert r.transfer("ag-1", "planner-1", rid="a").status == "OK" and r.revoke("planner-1", "e").status == "OK"
    assert r.transfer("ag-1", "planner-1", rid="b").status == "DENIED"
    seqs = {m["data"].get("request_id", m["data"].get("op")): m["seq"] for m in marks(r) if m["ref"] in ("commit", "authority")}
    assert seqs["a"] < seqs["revoke"] and "b" not in seqs


# ---- R24-4 explicit conflict, nothing granted by fallback -----------------------------------------------------------------
def test_r24_4_explicit_reasons_and_no_fallback(rig):
    assert rig.delegate("planner-1", edge("e1", "planner-1", "ag-1")).status == "OK"
    assert rig.delegate("ag-1", edge("e2", "ag-1", "ag-2", "e1")).status == "OK"
    h = head(rig)
    cases = [("planner-1", edge("e1", "planner-1", "ag-3"), "INVALID", "duplicate_edge"),
             ("ag-2", edge("c1", "ag-2", "planner-1", "e2"), "INVALID", "delegation_cycle"),
             ("ag-2", edge("c2", "ag-2", "ag-1", "e2"), "INVALID", "delegation_cycle"),
             ("ag-1", edge("c3", "ag-1", "ag-1", "e1"), "INVALID", "delegation_cycle"),
             ("ag-1", edge("c4", "ag-1", "ag-3", "nope"), "INVALID", "unknown_parent"),
             ("planner-1", edge("c5", "planner-1", "agent-1"), "INVALID", "static_delegate"),
             ("planner-1", edge("c6", "planner-1", "ghost"), "INVALID", "unknown_principal"),
             ("ag-3", edge("c7", "ag-3", "ag-4", "e1"), "INVALID", "unknown_parent"),  # G3 (PROT-H26 s3.1, Q9): e1 is hidden from ag-3 -> answered as absent
             ("planner-1", {"id": "bad"}, "INVALID", "schema")]
    for who, e, st, why in cases:
        res = rig.delegate(who, e)
        assert (res.status, res.body["reason"]) == (st, why), (e["id"], res)
    nr = edge("nr", "planner-1", "ag-5", redelegable=False)
    assert rig.delegate("planner-1", nr).status == "OK"
    assert rig.delegate("ag-5", edge("c8", "ag-5", "ag-6", "nr")).body["reason"] == "not_redelegable"
    assert rig.revoke("planner-1", "nr").status == "OK"
    assert rig.delegate("ag-5", edge("c9", "ag-5", "ag-6", "nr")).body["reason"] in ("parent_invalid", "not_redelegable")
    assert marks(rig, h, "authority")[-1]["data"]["op"] == "revoke" and len(marks(rig, h, "authority")) == 2  # only nr + its revoke
    # wrong on_behalf_of: naming a root that issued nothing is explicit DENIED, never a fallback to the subject's own authority
    h = head(rig)
    for sub, obo in (("ag-1", "junior-1"), ("planner-1", "junior-1"), ("ag-1", "ag-1"), ("ag-1", "ghost"), ("ag-3", "planner-1")):
        res = rig.transfer(sub, obo)
        assert (res.status, res.body["reason"]) == ("DENIED", "no_valid_path"), (sub, obo, res)
    assert zero_change(rig, h)


def test_r24_4_depth_overflow(tmp_path):
    a = v2_mfg()
    for i in range(7, 12):
        a["principals"].append({"id": f"ag-{i}", "kind": "agent", "roles": [], "relations": [], "delegated_by": None})
    r = G2Rig(tmp_path, auth=a)
    ids = ["planner-1"] + [f"ag-{i}" for i in range(1, 12)]
    parent = None
    for d in range(1, 10):
        res = r.delegate(ids[d - 1], edge(f"d{d}", ids[d - 1], ids[d], parent))
        if d <= 8:
            assert res.status == "OK", (d, res)
        parent = f"d{d}"
    assert (res.status, res.body["reason"]) == ("INVALID", "depth_exceeded")
    assert r.transfer("ag-8", "planner-1").status == "OK"  # depth-8 holder works through all eight scopes


# ---- R24-5 durability ----------------------------------------------------------------------------------------------------
def test_r24_5_edges_and_revocations_survive_crash_restart(rig):
    assert rig.delegate("planner-1", edge("e1", "planner-1", "ag-1")).status == "OK"
    assert rig.delegate("planner-1", edge("e2", "planner-1", "ag-2")).status == "OK"
    rig.dep.crash()
    rig.dep.restart()
    assert rig.transfer("ag-1", "planner-1").status == "OK"
    # after_commit crash of a revoke leaves it effective
    rig.dep.arm_crash("after_commit")
    assert rig.revoke("planner-1", "e1", rid="rv1").status == "UNKNOWN"
    rig.dep.restart()
    assert rig.transfer("ag-1", "planner-1").status == "DENIED"
    assert rig.revoke("planner-1", "e1", rid="rv1").status == "OK"  # the crashed request id returns its stored result
    assert len([m for m in marks(rig, 0, "authority") if m["data"].get("op") == "revoke"]) == 1  # one revoke ever
    # before_commit crash leaves it absent
    rig.dep.arm_crash("before_commit")
    assert rig.revoke("planner-1", "e2", rid="rv2").status == "UNKNOWN"
    rig.dep.restart()
    assert rig.transfer("ag-2", "planner-1").status == "OK"
    assert len([m for m in marks(rig, 0, "authority") if m["data"].get("op") == "revoke"]) == 1
    rig.dep.arm_crash("after_commit")  # a delegate crashed after commit is effective too
    assert rig.delegate("planner-1", edge("e3", "planner-1", "ag-3"), rid="dl3").status == "UNKNOWN"
    rig.dep.restart()
    assert rig.transfer("ag-3", "planner-1").status == "OK"
    assert rig.delegate("planner-1", edge("e3", "planner-1", "ag-3"), rid="dl3").status == "OK"


# ---- R24-6 historical authority ----------------------------------------------------------------------------------------------
def test_r24_6_authority_used_is_historical_and_never_relegitimises(rig):
    assert rig.delegate("planner-1", edge("e", "planner-1", "ag-1")).status == "OK"
    v1 = rig.dep.authority_version()
    assert rig.transfer("ag-1", "planner-1", rid="used1").status == "OK"
    rig.clock.advance(3)
    assert rig.revoke("planner-1", "e").status == "OK"
    assert rig.dep.authority_version() != v1
    res = rig.dep.authority_used("used1")
    commit = next(m for m in marks(rig, 0, "commit") if m["data"]["request_id"] == "used1")
    assert res.status == "OK" and res.body == {"authority_version": v1, "world_seq": commit["seq"], "tick": commit["tick"],
                                               "path": ["e"], "on_behalf_of": "planner-1"}
    assert rig.dep.authority_used("used1").body == res.body  # unchanged after the revocation
    assert rig.dep.authority_used("never").body == {"reason": "unknown_request"}
    h = head(rig)
    assert rig.transfer("ag-1", "planner-1", rid="used1b").status == "DENIED" and zero_change(rig, h)
    assert rig.dep.authority_used("used1b").status == "INVALID"  # a refused request was never committed


# ---- R24-7 safe progress ----------------------------------------------------------------------------------------------------
def test_r24_7_unaffected_requests_all_commit_while_a_revocation_races(rig):
    assert rig.delegate("planner-1", edge("a", "planner-1", "ag-1")).status == "OK"
    assert rig.delegate("planner-1", edge("b", "planner-1", "ag-2")).status == "OK"
    out, bar = [], threading.Barrier(5)

    def legit(i):
        bar.wait()
        out.append(rig.transfer("ag-2", "planner-1", rid=f"b{i}", args={**TR, "quantity": 10 + i}))

    def rev():
        bar.wait()
        out.append(rig.revoke("planner-1", "a"))
    ts = [threading.Thread(target=legit, args=(i,)) for i in range(4)] + [threading.Thread(target=rev)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(r.status == "OK" for r in out)  # none of the unaffected requests was refused or made UNAVAILABLE
    assert rig.transfer("ag-1", "planner-1").status == "DENIED"  # and the revocation took effect (negative)


def test_edge_requests_through_the_generated_tool_surface(rig):
    assert rig.delegate("planner-1", edge("e", "planner-1", "ag-1")).status == "OK"
    tok = rig.token("ag-1")
    res, eff = rig.effects_of(lambda: rig.dep.call_tool(tok, "transfer_inventory", TR, on_behalf_of="planner-1", request_id="tool1"))
    assert res.status == "OK" and len(eff) == 1  # via the same commit path as direct()
    assert [t.name for t in rig.dep.tools(tok)] == ["transfer_inventory"]  # G3 (PROT-H26 3.4): tools = operations the subject OR its live edges could be granted
    assert rig.revoke("planner-1", "e").status == "OK"
    res, eff = rig.effects_of(lambda: rig.dep.call_tool(tok, "transfer_inventory", {**TR, "quantity": 7}, on_behalf_of="planner-1",
                                                        request_id="tool2"))
    assert res.status == "DENIED" and eff == []
