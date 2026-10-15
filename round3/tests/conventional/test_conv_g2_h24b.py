"""PROT-H24 R24-5..7 and the four H24 mutants (conventional)."""
import threading

import pytest

from conv_g2_util import PART, TRANSFER, WH, edge, make_g2
from r3_shared.world import diff

PLANNER, NOBODY, JUNIOR = "planner-1", "nobody-1", "junior-1"


@pytest.fixture
def rig(tmp_path):
    r = make_g2(tmp_path)
    yield r
    r.close()


def setup_edge(r):
    assert r.dep.delegate(r.token(PLANNER), edge("e1", PLANNER, NOBODY), "d0").status == "OK"


def use(r, rid, qty=10):
    return r.dep.direct(r.token(NOBODY), "transfer_inventory", {**TRANSFER, "quantity": qty}, PLANNER, rid)


# ---- R24-5 durability -------------------------------------------------------------------------------------------
def test_r24_5_edges_survive_crash_and_restart(rig):
    setup_edge(rig)
    rig.dep.crash()
    assert use(rig, "dead").body["reason"] == "crashed"
    rig.dep.restart()
    assert use(rig, "alive").status == "OK" and rig.dep.authority_state()["capabilities"][0]["id"] == "e1"


def test_r24_5_after_commit_crash_of_revoke_leaves_it_revoked(rig):
    setup_edge(rig)
    rig.dep.arm_crash("after_commit")
    r = rig.dep.revoke(rig.token(PLANNER), "e1", "rv")
    assert (r.status, r.body["reason"]) == ("UNKNOWN", "crashed")
    rig.dep.restart()
    before = rig.snap()
    assert use(rig, "u").body["reason"] == "no_valid_path" and diff(before, rig.snap()) == []
    again = rig.dep.revoke(rig.token(PLANNER), "e1", "rv")  # retry of the crashed request: its stored result
    assert again.status == "OK" and [m["data"]["op"] for m in rig.marks("authority")].count("revoke") == 1


def test_r24_5_before_commit_crash_of_revoke_leaves_the_edge_valid(rig):
    setup_edge(rig)
    n = len(rig.marks("authority"))
    rig.dep.arm_crash("before_commit")
    assert rig.dep.revoke(rig.token(PLANNER), "e1", "rv").body["reason"] == "crashed"
    rig.dep.restart()
    assert len(rig.marks("authority")) == n and use(rig, "u").status == "OK"
    assert rig.dep.revoke(rig.token(PLANNER), "e1", "rv").status == "OK"  # the retry now takes effect
    assert use(rig, "u2", 2).status == "DENIED"


def test_r24_5_after_commit_crash_of_delegate_is_idempotent_on_retry(rig):
    rig.dep.arm_crash("after_commit")
    assert rig.dep.delegate(rig.token(PLANNER), edge("e1", PLANNER, NOBODY), "d0").status == "UNKNOWN"
    rig.dep.restart()
    r = rig.dep.delegate(rig.token(PLANNER), edge("e1", PLANNER, NOBODY), "d0")
    assert r.status == "OK" and len(rig.dep.authority_state()["capabilities"]) == 1


# ---- R24-6 historical authority ---------------------------------------------------------------------------------
def test_r24_6_authority_used_returns_the_relied_on_path_and_commit_point(rig):
    setup_edge(rig)
    rig.clock.advance(3)
    assert use(rig, "u1").status == "OK"
    v1 = rig.dep.authority_version()
    rig.dep.revoke(rig.token(PLANNER), "e1", "rv")
    u = rig.dep.authority_used("u1").body
    commit = next(m for m in rig.marks("commit") if m["data"]["request_id"] == "u1")
    assert u == {"authority_version": v1, "world_seq": commit["seq"], "tick": 5, "path": ["e1"], "on_behalf_of": PLANNER}
    assert rig.dep.authority_used("u1").body == u  # the historical answer does not change after the revoke...
    assert use(rig, "u2", 2).status == "DENIED"  # ...and never re-legitimises the path now
    assert rig.dep.authority_used("never") == rig.dep.authority_used("u2")  # a refused request has no commit point
    assert rig.dep.authority_used("never").body["reason"] == "unknown_request"


def test_r24_6_base_authority_request_reports_an_empty_path(rig):
    r = rig.dep.direct(rig.token(PLANNER), "transfer_inventory", TRANSFER, None, "own")
    assert r.status == "OK" and rig.dep.authority_used("own").body["path"] == []


# ---- R24-7 safe progress ----------------------------------------------------------------------------------------
def test_r24_7_unrelated_revocation_never_blocks_legitimate_requests(rig):
    setup_edge(rig)
    rig.dep.delegate(rig.token(PLANNER), edge("e9", PLANNER, JUNIOR), "d9")
    out, errs = [], []

    def worker(i):
        try:
            out.append(use(rig, f"w{i}", 1).status)
        except Exception as exc:  # noqa: BLE001
            errs.append(exc)
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    rv = threading.Thread(target=lambda: out.append("rv:" + rig.dep.revoke(rig.token(PLANNER), "e9", "rv").status))
    for t in ts + [rv]:
        t.start()
    for t in ts + [rv]:
        t.join()
    assert not errs and sorted(out) == ["OK"] * 6 + ["rv:OK"]


# ---- the four H24 mutants: each demonstrably changes behaviour (the frozen corpus is the real kill) --------------
def build(tmp_path, mutants=()):
    r = make_g2(tmp_path, mutants=mutants, start=3)
    setup_edge(r)
    return r


@pytest.mark.parametrize("mutant,bug", [(None, False), ("non_attenuating_delegation", True)])
def test_mutant_non_attenuating_delegation(tmp_path, mutant, bug):
    r = build(tmp_path, [mutant] if mutant else [])
    try:
        wider = edge("w", NOBODY, JUNIOR, "e1", ops=("transfer_inventory", "expedite_purchase_order"))
        assert (r.dep.delegate(r.token(NOBODY), wider, "w").status == "OK") is bug  # issuance: subset check skipped
        narrow = edge("m", NOBODY, JUNIOR, "e1", res=({"type": "Warehouse", "keys": ["WH-B"]}, PART))
        assert r.dep.delegate(r.token(NOBODY), narrow, "m").status == "OK"
        # g (broader than its parent m) can only exist if issuance skipped the subset check; use then looks at g alone
        if bug:
            broad = edge("g", JUNIOR, "senior-1", "m", res=(WH, PART))
            assert r.dep.delegate(r.token(JUNIOR), broad, "g").status == "OK"
            res = r.dep.direct(r.token("senior-1"), "transfer_inventory", TRANSFER, PLANNER, "x")
            assert res.status == "OK"  # commits on WH-A although edge m (an ancestor) excludes it
        else:
            assert r.dep.delegate(r.token(JUNIOR), edge("g", JUNIOR, "senior-1", "m", res=(WH, PART)), "g").body["reason"] == "scope_amplification"
    finally:
        r.close()


@pytest.mark.parametrize("mutant,bug", [(None, False), ("stale_authority_cache", True)])
def test_mutant_stale_authority_cache(tmp_path, mutant, bug):
    r = build(tmp_path, [mutant] if mutant else [])
    try:
        assert use(r, "warm", 2).status == "OK"
        r.dep.revoke(r.token(PLANNER), "e1", "rv")
        res = use(r, "after", 2)
        assert (res.status == "OK") is bug, res  # the cached allow survives the revoke only in the mutant
    finally:
        r.close()


@pytest.mark.parametrize("mutant,bug", [(None, False), ("revoke_commit_reorder", True)])
def test_mutant_revoke_commit_reorder(tmp_path, mutant, bug):
    r = build(tmp_path, [mutant] if mutant else [])
    try:
        assert r.dep.revoke(r.token(PLANNER), "e1", "rv").status == "OK"  # acknowledged
        res = use(r, "after", 2)
        assert (res.status == "OK") is bug, res  # mutant: the revoke is applied only after this effect committed
        revoke_commit = [m["seq"] for m in r.marks("commit") if m["data"]["request_id"] == "rv"]
        effect_commit = [m["seq"] for m in r.marks("commit") if m["data"]["request_id"] == "after"]
        if bug:
            assert effect_commit and revoke_commit and effect_commit[0] < revoke_commit[0]  # log order contradicts real time
        else:
            assert not effect_commit and revoke_commit
        assert use(r, "later", 1).status == "DENIED"  # eventually effective in both builds
    finally:
        r.close()


@pytest.mark.parametrize("mutant,bug", [(None, False), ("expiry_inclusive", True)])
def test_mutant_expiry_inclusive(tmp_path, mutant, bug):
    r = make_g2(tmp_path, mutants=[mutant] if mutant else [], start=3)
    try:
        r.dep.delegate(r.token(PLANNER), edge("e1", PLANNER, NOBODY, expires=10), "d0")
        r.clock.advance(7)  # tick 10 == expires_at
        h = r.store.handle("seed")
        h.update("EvidenceSnapshot", "ES-1", {"snapshotObservedAt": 10})
        h.close()
        assert (use(r, "edge", 2).status == "OK") is bug
    finally:
        r.close()
