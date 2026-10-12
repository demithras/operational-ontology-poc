"""PROT-H29 R29-8..R29-11 on the Paladin variant: SIGKILL of a spawned host at crash points, resume in a NEW process over the surviving
stores (deploy(resume=True)), RC1 determinism / admissibility, RC2 equality, redelivery, B4 (never start empty). Truth = the world
store, the anchor and the ExternalWorld ledger, never the variant's own reports (those are COMPARED)."""
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from g5_rig import DEP, EXP, TR, G5Rig
from r3_shared.authsvc import doc_digest, in_force
from r3_shared.faultplane import CanonicalStateLost
from r3_shared.host import DeploymentProxy, HostDead
from r3_shared.recovery import canon_json, validate_recovery_view


@pytest.fixture
def rig():
    r = G5Rig(inproc=False)
    yield r
    r.finish()


def kill_at(rig, cp, rid, op="transfer_inventory", args=TR, sub="planner-1"):
    px = rig.host()
    px.arm(cp, rid)
    with pytest.raises(HostDead):
        px.direct(rig.token(sub), op, args, None, rid)
    return px


def ledger_rows(rig):
    con = sqlite3.connect(f"file:{rig.root / 'ext' / 'external.db'}?mode=ro", uri=True)
    try:
        return con.execute("SELECT correlation FROM effects ORDER BY seq").fetchall()
    finally:
        con.close()


def restrict(rig, frm, to):
    """P1g-7 restricted state: AUTH and every EXT outage + observer irrelevant (no read before the first API call); ANCHOR read-only."""
    rig.actl.outage(DEP, frm, to, "drop")
    for s in rig.systems["systems"]:
        rig.ctl.outage(s, DEP, frm, to)


def test_r29_8_kill_before_commit_leaves_nothing_and_redelivery_commits_exactly_once(rig):
    kill_at(rig, "CP1_before_commit", "k1")
    assert rig.commits() == []
    px = rig.host(resume=True)                                                   # a NEW process: nothing of the old one survives
    v = validate_recovery_view(px.recovery_view())
    assert v["committed"] == [] and v["intents"] == [] and v["authority"] == {"version": None, "lease_until": None}
    assert px.direct(rig.token("planner-1"), "transfer_inventory", TR, None, "k1").status == "OK"
    assert rig.commits() == ["k1"]
    px.dispatch_pending()
    assert [r[0] for r in ledger_rows(rig)] == ["k1#0"]                         # the intent registered before the aborted COMMIT was voided and re-made


def test_r29_8_kill_after_commit_before_anchor_is_in_doubt_not_ok_and_never_commits_twice(rig):
    kill_at(rig, "CP2_after_commit", "k2")
    assert rig.commits() == ["k2"]
    px = rig.host(resume=True)
    v = validate_recovery_view(px.recovery_view())
    assert [c["request_id"] for c in v["committed"]] == ["k2"]
    assert [(i["request_id"], i["state"]) for i in v["intents"]] == [("k2", "PENDING")]    # durable BEFORE the COMMIT: not lost with the ack
    again = px.direct(rig.token("planner-1"), "transfer_inventory", TR, None, "k2")
    assert (again.status, again.body) == ("UNKNOWN", {"reason": "in_doubt"})      # committed, never anchored: no OK without an anchor entry
    assert rig.commits() == ["k2"]
    assert px.dispatch_pending().body == {"submitted": 0}                        # no provable (anchored) decision envelope: the adapter is never called
    rig.tick(12, px)
    out = px.reconcile("k2", rig.clock.now() + 1).body["outcomes"]               # the observer sees no effect past the cap expiry (P1f-6 rule F)
    assert ledger_rows(rig) == [] and [o["state"] for o in out] == ["RECONCILED_FAILED"]


def test_r29_8_kill_after_anchor_append_redelivery_is_the_original_ok(rig):
    kill_at(rig, "CP3_after_anchor_append", "k3")
    px = rig.host(resume=True)
    again = px.direct(rig.token("planner-1"), "transfer_inventory", TR, None, "k3")
    assert again.status == "OK" and again.body.get("replayed") is True
    assert rig.commits() == ["k3"]


def copy_stores(rig, name):
    d = rig.root / name
    d.mkdir()
    for f in rig.root.glob("world.db*"):
        shutil.copy2(f, d / f.name)
    for f in rig.root.glob("hist.db*"):
        shutil.copy2(f, d / f.name)
    return d


def host_on(rig, d, tick):
    s = rig.spec(True, tick)
    s["world_path"], s["history_path"] = str(d / "world.db"), str(d / "hist.db")
    w = d / "work"
    w.mkdir()
    px = DeploymentProxy.start("paladin", (), s, str(w), extra_paths=[str(Path(rig.root).parents[0]), str(Path(__file__).parent)])
    rig.hosts.append(px)
    return px


def test_r29_9_r29_10_rc1_two_hosts_from_byte_copies_return_byte_identical_views_equal_to_the_oracle_set(rig):
    kill_at(rig, "CP2_after_commit", "c1")
    rig.tick(3)
    restrict(rig, 3, 15)                                                          # RC1: AUTH, EXT down; the anchor is not appended to
    copy = copy_stores(rig, "copyB")
    a, b = rig.host(resume=True, tick=3), host_on(rig, copy, 3)
    va, vb = a.recovery_view(), b.recovery_view()
    assert canon_json(validate_recovery_view(va)) == canon_json(validate_recovery_view(vb))   # R29-9 byte equality
    assert [c["request_id"] for c in va["committed"]] == rig.commits() == ["c1"]    # R29-10: committed == the world's own commit set
    assert va["authority"] == {"version": None, "lease_until": None}                # unverified, never a retained version
    assert [i["state"] for i in va["intents"]] == ["PENDING"]                        # admissible: last durable snapshot or PENDING/UNKNOWN


def test_r29_11_rc2_view_equals_the_prediction_from_the_services_and_redelivery_adds_nothing(rig):
    px = rig.host()
    tok = rig.token("planner-1")
    assert px.direct(tok, "transfer_inventory", TR, None, "q1").status == "OK"
    assert px.direct(tok, "expedite_purchase_order", EXP, None, "q2").status == "OK"
    px.arm("CP2_after_commit", "q3")
    with pytest.raises(HostDead):
        px.direct(tok, "reschedule_work_order", {"work_order_id": "WO-43", "new_planned_start": 55}, None, "q3")
    rig.tick(2)
    restrict(rig, 2, 4)
    px2 = rig.host(resume=True, tick=2)
    rc1 = px2.recovery_view()
    assert [c["request_id"] for c in rc1["committed"]] == ["q1", "q2", "q3"] and rc1["authority"]["version"] is None
    rig.tick(3, px2)                                                              # t=5: every fault healed (windows are [2,4))
    assert px2.dispatch_pending().body["submitted"] == 2                          # q3 was never anchored: no provable envelope, no dispatch
    rig.tick(12, px2)
    for rid in ("q1", "q2", "q3"):
        assert px2.reconcile(rid, rig.clock.now() + 1).status == "OK"
    assert px2.read(tok, "list", {"type": "Part"}).status == "OK"                    # the AUTH-dependent probe read
    rc2 = validate_recovery_view(px2.recovery_view())
    t = rig.clock.now()
    marks = [x["data"] for x in __import__("r3_shared.world", fromlist=["WorldReader"]).WorldReader(str(rig.world_path)).log() if x["kind"] == "mark" and x["ref"] == "commit"]
    A = in_force(rig.actl.log()["versions"], t)
    expected = {"form": "r3-recovery-1", "authority": {"version": A, "lease_until": t + 4}, "approvals_open": [],
                "committed": [{"request_id": m["request_id"], "world_seq": c["world_seq"], "authority_version": m["authority_version"]}
                              for m, c in zip(marks, rc2["committed"])],
                "intents": [{"request_id": r, "effect_index": 0, "system": s, "chain_ids": 1, "state": "RECONCILED_SUCCESS" if r != "q3" else "RECONCILED_FAILED",
                             "confidence": "full" if s != "MES" else "low"} for r, s in (("q1", "WMS"), ("q2", "ERP"), ("q3", "MES"))]}
    assert canon_json(rc2) == canon_json(expected)
    assert sorted(r[0] for r in ledger_rows(rig)) == ["q1#0", "q2#0"]               # every anchored effect exactly once, the unanchored one never
    head = rig.reader.snapshot()["log_head"]
    n_rows = len(ledger_rows(rig))
    for rid, op, args in (("q1", "transfer_inventory", TR), ("q2", "expedite_purchase_order", EXP)):
        again = px2.direct(tok, op, args, None, rid)
        assert again.status == "OK" and again.body.get("replayed") is True        # the original decision
    assert px2.direct(tok, "reschedule_work_order", {"work_order_id": "WO-43", "new_planned_start": 55}, None, "q3").status == "UNKNOWN"
    assert rig.reader.snapshot()["log_head"] == head and len(ledger_rows(rig)) == n_rows   # zero new world rows, zero new ledger rows


def test_b4_resume_over_lost_stores_raises_canonical_state_lost_and_never_starts_empty(rig):
    kill_at(rig, "CP2_after_commit", "b1")
    for f in list(rig.root.glob("world.db*")) + list(rig.root.glob("hist.db*")):
        f.unlink()
    with pytest.raises(CanonicalStateLost):
        rig.host(resume=True)
    assert not rig.world_path.exists() or rig.commits() == []                       # nothing was re-created, nothing re-committed


def test_b4_in_process_empty_history_and_missing_ledger_raise(rig):
    from paladin.variant import PaladinVariant
    from r3_shared.histstore import HistoryStore
    from r3_shared.world import WorldStore
    r = G5Rig()
    try:
        r.dep.direct(r.token("planner-1"), "transfer_inventory", TR, request_id="e1")
        empty = HistoryStore(str(r.root / "other.db"))
        with pytest.raises(CanonicalStateLost):
            PaladinVariant().deploy(r.domain, r.store.handle_factory(), r.idp.verifier(), r.ops, r.auth0, r.clock, history=empty,
                                    anchor=r.anchor.client(), authority_source=r.binding(), resume=True)
        with pytest.raises(CanonicalStateLost):
            PaladinVariant().deploy(r.domain, r.store.handle_factory(), r.idp.verifier(), r.ops, r.auth0, r.clock,
                                    state_dir=str(r.root / "nope"), authority_source=r.binding(), resume=True)
        ok = r.deploy(resume=True)                                                    # the real stores: resumes, E1 is committed
        assert [c["request_id"] for c in ok.recovery_view()["committed"]] == ["e1"]
    finally:
        r.finish()


def test_f8_tampered_authority_record_never_yields_an_ok_after_resume(rig):
    px = rig.host()
    tok = rig.token("planner-1")
    assert px.direct(tok, "transfer_inventory", TR, None, "t1").status == "OK"
    px.kill()
    from r3_shared.histstore import HistoryStore
    h = HistoryStore(str(rig.root / "hist.db"))
    for k in h.keys("auth/"):
        h.delete(k)                                                               # the content-addressed authority copy is gone
    px2 = rig.host(resume=True)
    res = px2.direct(tok, "transfer_inventory", {**TR, "quantity": 2}, None, "t2")
    assert res.status != "OK" and "t2" not in rig.commits()                        # fail closed, zero effects
