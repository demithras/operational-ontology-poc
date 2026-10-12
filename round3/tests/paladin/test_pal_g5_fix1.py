"""Gate 5 fix1 (errata G5-E10..E14) on the Paladin variant: bound authority version, canonical approval fingerprint, completion of a lost
anchor entry (commit in the world, never anchored), invalid/unknown tokens while blocked, INVALID reasons while blocked."""
import hashlib
import json
import sqlite3

import pytest

from g5_rig import DEP, EXP, TR, G5Rig
from r3_shared.authsvc import in_force
from r3_shared.extadapter import canon_json
from r3_shared.histstore import HistoryStore
from r3_shared.host import HostDead
from r3_shared.recovery import INPUT_INVALID_REASONS, validate_recovery_view, validate_reply


@pytest.fixture
def rig():
    r = G5Rig(inproc=False)
    yield r
    r.finish()


@pytest.fixture
def irig():
    r = G5Rig()
    yield r
    r.finish()


def kill_at(rig, cp, rid, op="transfer_inventory", args=TR):
    px = rig.host()
    px.arm(cp, rid)
    try:
        px.direct(rig.token("planner-1"), op, args, None, rid)
    except HostDead:
        pass
    px.wait_dead()


def ext_rows(rig):
    con = sqlite3.connect(f"file:{rig.root / 'ext' / 'external.db'}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute("SELECT correlation FROM effects ORDER BY seq")]
    finally:
        con.close()


def pend_keys(rig):
    return HistoryStore(str(rig.root / "hist.db")).keys("led/pend/")


# ---- G5-E12 -------------------------------------------------------------------------------------------------------------
def test_e12_anchor_down_at_resume_then_heal_redelivery_is_the_original_decision_with_zero_new_rows(rig):
    kill_at(rig, "CP2_after_commit", "a1")
    stream = HistoryStore(str(rig.root / "hist.db")).get("meta/stream").decode()
    assert pend_keys(rig) == ["led/pend/a1"]                                     # the journal of the unanchored commit survives the kill
    rig.nctl.partition(stream, 1, 5, "drop")
    rig.tick(1)
    px = rig.host(resume=True, tick=1)
    during = px.direct(rig.token("planner-1"), "transfer_inventory", TR, None, "a1")
    ok_forms = (("UNKNOWN", {"reason": "in_doubt"}), ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "ANCHOR"}))
    assert (during.status, during.body) in ok_forms and rig.commits() == ["a1"]   # R29-7 admissible before heal, never OK, never a 2nd commit
    assert px.dispatch_pending().body == {"submitted": 0}                       # no provable decision envelope yet: the adapter is not called
    assert ext_rows(rig) == []
    rig.tick(5, px)                                                              # RC2: every fault healed
    head = rig.reader.snapshot()["log_head"]
    again = px.direct(rig.token("planner-1"), "transfer_inventory", TR, None, "a1")   # the first governed call after heal completes the anchor
    assert again.status == "OK" and again.body.get("replayed") is True
    assert pend_keys(rig) == [] and rig.reader.snapshot()["log_head"] == head and rig.commits() == ["a1"]
    assert px.dispatch_pending().body == {"submitted": 1}
    rig.tick(12, px)
    assert px.reconcile("a1", rig.clock.now() + 1).status == "OK"
    rows = len(ext_rows(rig))
    assert ext_rows(rig) == ["a1#0"]
    again = px.direct(rig.token("planner-1"), "transfer_inventory", TR, None, "a1")
    assert again.status == "OK" and len(ext_rows(rig)) == rows and rig.reader.snapshot()["log_head"] == head   # zero new world / ledger rows


def test_e12_dispatch_pending_alone_completes_the_anchor_after_heal(rig):
    kill_at(rig, "CP2_after_commit", "a2")
    stream = HistoryStore(str(rig.root / "hist.db")).get("meta/stream").decode()
    rig.nctl.partition(stream, 1, 3, "drop")
    rig.tick(1)
    px = rig.host(resume=True, tick=1)
    assert px.dispatch_pending().body == {"submitted": 0}
    rig.tick(3, px)
    assert px.dispatch_pending().body == {"submitted": 1}                       # no client call needed: the dispatcher heals the anchor too
    assert pend_keys(rig) == []


def test_e12_negative_anchored_commit_leaves_no_journal_and_a_rolled_back_request_leaves_none(rig):
    px = rig.host()
    assert px.direct(rig.token("planner-1"), "transfer_inventory", TR, None, "n1").status == "OK"
    bad = px.direct(rig.token("planner-1"), "transfer_inventory", {**TR, "quantity": 10 ** 9}, None, "n2")   # refused by the rules: no commit
    assert bad.status != "OK" and "n2" not in rig.commits()
    assert pend_keys(rig) == []                                                  # nothing to complete: the sweep has no false positives


def test_e12_a_request_without_request_id_is_refused_before_any_commit_so_there_is_nothing_to_anchor(irig):
    res = irig.dep.direct(irig.token("planner-1"), "transfer_inventory", TR)
    assert res.status == "INVALID" and irig.commits() == []
    assert irig.dep._c.history.keys("led/pend/") == []


def test_e12_unanchored_authority_change_is_completed_at_first_call_after_resume_like_a_request(monkeypatch):
    import copy

    import g5_rig
    from g2_rig import edge
    base = g5_rig.load_auth_spec

    def with_delegable_planner(name):   # the G5 document issues no edge by itself: add one delegable grant (neutral extension)
        a = copy.deepcopy(base(name))
        a["grants"].append({"id": "g5-planner-transfer", "operation": "transfer_inventory", "effect": "allow", "delegable": True,
                            "origin": "neutral-extension", "principal": {"on_type": "Warehouse", "relation": "planner"},
                            "resource": {"type": "Warehouse"}})
        return a
    monkeypatch.setattr(g5_rig, "load_auth_spec", with_delegable_planner)
    rig = G5Rig(inproc=False)
    try:
        px = rig.host()
        px.arm("CP2_after_commit", "m1")
        with pytest.raises(HostDead):
            px.delegate(rig.token("planner-1"), edge("e1", "planner-1", "junior-1"), "m1")
        px.wait_dead()
        assert rig.commits() == ["m1"] and pend_keys(rig) == ["led/pend/m1"]
        px2 = rig.host(resume=True)
        assert pend_keys(rig) == ["led/pend/m1"]                                 # G5-E25: nothing is anchored before the first API call
        again = px2.delegate(rig.token("planner-1"), edge("e1", "planner-1", "junior-1"), "m1")
        assert again.status == "OK" and rig.commits() == ["m1"]                  # the original decision, no second commit
        assert pend_keys(rig) == []                                              # the delegate decision is anchored by the first call
        assert len(HistoryStore(str(rig.root / "hist.db")).keys("env/")) == 1    # exactly one decision envelope exists for it
    finally:
        rig.finish()


# ---- G5-E13 / G5-E14 ----------------------------------------------------------------------------------------------------
def test_e13_invalid_token_with_a_down_dependency_is_unavailable_naming_it_and_healthy_it_is_denied(irig):
    healthy = irig.dep.direct("not-a-token", "transfer_inventory", TR, request_id="t0")
    assert healthy.status == "DENIED" and "dependency" not in healthy.body      # deps up: the H23-H28 behaviour is unchanged
    irig.actl.outage(DEP, 1, 20, "drop")
    irig.tick(6)
    res = irig.dep.direct("not-a-token", "transfer_inventory", TR, request_id="t1")
    assert (res.status, res.body) == ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "AUTH"})
    validate_reply(res.status, res.body)
    assert irig.commits() == []


def test_e13_unknown_token_with_anchor_down_names_the_anchor(irig):
    irig.nctl.partition(irig.dep._c.prov.stream, 1, 5, "drop")
    irig.tick()
    res = irig.dep.direct("garbage", "transfer_inventory", TR, request_id="t2")
    assert (res.status, res.body) == ("UNAVAILABLE", {"reason": "dependency_unavailable", "dependency": "ANCHOR"})


def test_e14_invalid_while_blocked_uses_the_input_invalid_reason_set_for_authenticated_callers(irig):
    bad = {**TR, "quantity": "many"}
    healthy = irig.dep.direct(irig.token("planner-1"), "transfer_inventory", bad, request_id="i0")
    assert healthy.status == "INVALID" and healthy.body["reason"] not in INPUT_INVALID_REASONS   # legacy string kept on the healthy path
    irig.actl.outage(DEP, 1, 20, "drop")
    irig.tick(6)
    res = irig.dep.direct(irig.token("planner-1"), "transfer_inventory", bad, request_id="i1")
    assert res.status == "INVALID" and res.body["reason"] in INPUT_INVALID_REASONS and "dependency" not in res.body
    ok = irig.dep.direct(irig.token("planner-1"), "transfer_inventory", TR, request_id="i2")   # a VALID request stays blocked
    assert (ok.status, ok.body["dependency"]) == ("UNAVAILABLE", "AUTH")


def test_e14_unauthenticated_callers_get_the_dependency_reply_even_for_malformed_input(irig):
    """Uniform rule: the frozen check order is token -> schema -> authority (PROT-H26 s3.2) and E13 pins an invalid token to
    UNAVAILABLE while blocked; an INVALID for a caller whose token is unverified would reorder the gates. R29-7 allows either
    reply here (an input error 'stays allowed'); the variant always answers UNAVAILABLE naming the down node."""
    irig.actl.outage(DEP, 1, 20, "drop")
    irig.tick(6)
    res = irig.dep.direct("not-a-token", "transfer_inventory", {**TR, "quantity": "many"}, request_id="u1")
    assert (res.status, res.body["dependency"]) == ("UNAVAILABLE", "AUTH")


# ---- G5-E10 / G5-E11 ----------------------------------------------------------------------------------------------------
def test_e10_committed_authority_version_is_the_leased_digest(irig):
    assert irig.dep.direct(irig.token("planner-1"), "transfer_inventory", TR, request_id="v1").status == "OK"
    irig.tick(1)
    v = validate_recovery_view(irig.dep.recovery_view())
    assert [c["authority_version"] for c in v["committed"]] == [in_force(irig.actl.log()["versions"], 0)]


def fp(requester, obo, op, args):
    return hashlib.sha256(canon_json({"subject": requester, "on_behalf_of": obo, "operation": op, "inputs": args}).encode()).hexdigest()


def test_e11_approvals_open_is_the_canonical_fingerprint_deduplicated_sorted_with_non_ascii_args(irig):
    sup, args2 = irig.token("supervisor-1"), {"po_id": "PO-ü992", "expedite_fee": 900}
    for args in ({"po_id": "PO-992", "expedite_fee": 900}, args2, args2):
        assert irig.dep.approve(sup, "expedite_purchase_order", args, "planner-1").status == "OK"
    got = irig.dep.recovery_view()["approvals_open"]
    want = sorted({fp("planner-1", None, "expedite_purchase_order", {"po_id": "PO-992", "expedite_fee": 900}),
                   fp("planner-1", None, "expedite_purchase_order", args2)})
    assert got == want and len(got) == 2                                         # two distinct approvals, the repeated one de-duplicated
    escaped = hashlib.sha256(json.dumps({"subject": "planner-1", "on_behalf_of": None, "operation": "expedite_purchase_order",
                                         "inputs": args2}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert escaped not in got                                                    # NOT the ensure_ascii form: canon_json keeps non-ASCII


def test_e11_a_consumed_approval_leaves_approvals_open(irig):
    args = {"po_id": "PO-992", "expedite_fee": 900}
    assert irig.dep.approve(irig.token("supervisor-1"), "expedite_purchase_order", args, "planner-1").status == "OK"
    assert irig.dep.recovery_view()["approvals_open"] == [fp("planner-1", None, "expedite_purchase_order", args)]
    assert irig.dep.direct(irig.token("planner-1"), "expedite_purchase_order", args, request_id="c1").status == "OK"
    assert irig.dep.recovery_view()["approvals_open"] == []


# ---- G5-E25 / P1g-2: resume appends nothing to the anchor before the first API call after recovery_view() ---------------
def test_e25_resume_over_unanchored_commit_keeps_anchor_head_through_recovery_view_then_completes_at_first_call(rig):
    kill_at(rig, "CP2_after_commit", "e25")
    stream = HistoryStore(str(rig.root / "hist.db")).get("meta/stream").decode()
    assert pend_keys(rig) == ["led/pend/e25"]
    head0 = rig.anchor.client().head(stream)
    rig.tick(1)
    px = rig.host(resume=True, tick=1)
    v1 = px.recovery_view()
    v2 = px.recovery_view()
    assert v1 == v2                                                              # read-only and deterministic
    assert rig.anchor.client().head(stream) == head0                             # restricted phase: no anchor append
    assert pend_keys(rig) == ["led/pend/e25"]                                    # the journal is untouched too
    again = px.direct(rig.token("planner-1"), "transfer_inventory", TR, None, "e25")   # first API call after recovery_view()
    assert again.status == "OK" and again.body.get("replayed") is True
    assert pend_keys(rig) == [] and rig.anchor.client().head(stream) != head0    # the missing entry is completed now
    assert rig.commits() == ["e25"]
