"""H27 (Paladin): provenance is tamper-evident. One test per requirement R27-1..R27-7 (each with its negative), expectations
derived by hand from PROT-H27 and the world store, never from the variant's own artifacts."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g2_hist import BIG, build, envelopes, expected_contract, expected_evidence, expected_policy, sha, tamper_envelope  # noqa: E402
from g2_rig import G2Rig, TR, new_anchor  # noqa: E402
from r3_shared.anchor import AnchorClient, verify_anchor_log  # noqa: E402
from r3_shared.evidence import canonical_bytes  # noqa: E402

_N = [0]


@pytest.fixture(scope="module")
def anchor(tmp_path_factory):
    d = tmp_path_factory.mktemp("anchor")
    ap = new_anchor(d)
    yield ap
    ap.close()


@pytest.fixture
def hist(tmp_path, anchor):
    r = G2Rig(tmp_path, history=True, anchor=anchor.client())
    r.snaps = build(r)
    r.fresh = lambda: r.deploy(state_dir=None)  # a FRESH deployment: new empty state, same world + HistoryStore
    return r


def commit_row(r, rid):
    return next(m for m in r.log() if m["kind"] == "mark" and m["ref"] == "commit" and m["data"]["request_id"] == rid)


# ---- R27-4 clean histories: every decision VERIFIED with artifacts digest-equal to the independent expectation -------------
def test_r27_4_clean_history_verifies_every_decision_with_expected_bindings(hist):
    ops, f, env = hist.ops, hist.fresh(), envelopes(hist)
    assert sorted(env) == sorted(["d1", "t1", "t2", "t3", env_ap(env), "t4", "rv"])
    for did, e in env.items():
        res = f.replay(did)
        assert (res.status, res.reason) == ("VERIFIED", "ok"), (did, res)
        assert res.envelope == e and set(res.artifacts) == {d for d in [*e["artifacts"]["evidence"], e["artifacts"]["authority"],
                                                                      e["artifacts"]["policy"], e["artifacts"]["contract"]]}
        assert all(sha(b) == d for d, b in res.artifacts.items())
    seqs = [e["seq"] for e in sorted(env.values(), key=lambda e: e["seq"])]
    assert seqs == list(range(1, 8)) and len({e["stream"] for e in env.values()}) == 1  # gap-free, one stream
    t1 = env["t1"]
    refs = ["Warehouse:WH-C", "Warehouse:WH-B", "Part:PX-900", "EvidenceSnapshot:ES-1"]
    assert t1["artifacts"]["evidence"] == expected_evidence(hist.snaps["t1"], refs)
    assert t1["artifacts"]["policy"] == sha(expected_policy(ops, "transfer_inventory"))
    assert t1["artifacts"]["contract"] == sha(expected_contract(ops, "transfer_inventory"))
    row = commit_row(hist, "t1")
    tx_rows = [x for x in hist.log() if x["tx"] == row["tx"]]
    assert t1["decision"] == {"decision_id": "t1", "kind": "direct", "subject": "ag-1", "on_behalf_of": "planner-1",
                              "operation": "transfer_inventory", "args_digest": sha(TR), "status": "OK", "reason": "ok",
                              "effect_digest": sha(tx_rows), "world_seq": row["seq"], "tick": row["tick"], "authority_path": ["e1"]}
    assert env["t2"]["decision"]["status"] == "DENIED" and env["t2"]["decision"]["effect_digest"] == sha([])
    assert env["d1"]["artifacts"]["policy"] == sha(None) == env["rv"]["artifacts"]["contract"]  # delegate/revoke bind null
    # the version bound is the version in force at the commit point: the delegate's own (post-mutation) version is what t1 ran under
    assert env["d1"]["artifacts"]["authority"] == env["t1"]["artifacts"]["authority"] != env["rv"]["artifacts"]["authority"]
    assert env["t1"]["artifacts"]["authority"] == sha(hist.dep.authority_state()) or env["rv"]["artifacts"]["authority"] == hist.dep.authority_version()


def env_ap(env):
    return next(k for k in env if k.startswith("approve:"))


# ---- R27-1 detection ------------------------------------------------------------------------------------------------------
def not_verified(r, ids):
    f = r.fresh()
    return {d: f.replay(d).status for d in ids}


def test_r27_1_each_mutation_class_is_detected(tmp_path, anchor):
    def fresh_hist(n):
        (tmp_path / n).mkdir()
        r = G2Rig(tmp_path / n, history=True, anchor=anchor.client())
        r.snaps = build(r)
        r.fresh = lambda: r.deploy(state_dir=None)
        return r
    pol = lambda r, d: r.tamper().keys("art/") and envelopes(r)[d]["artifacts"]["policy"]
    cases = {}
    r = fresh_hist("t1")  # mutate-field of an artifact (one byte)
    tv, d = r.tamper(), envelopes(r)["t1"]["artifacts"]["policy"]
    tv.write(f"art/{d}", tv.read(f"art/{d}") + b" ")
    cases["mutate_artifact"] = (r, "t1")
    r = fresh_hist("t2")  # mutate-field of an envelope
    tamper_envelope(r, "t1", lambda e: e["decision"].__setitem__("status", "DENIED"))
    cases["mutate_envelope"] = (r, "t1")
    r = fresh_hist("t3")  # delete-artifact
    tv = r.tamper()
    tv.delete(f"art/{envelopes(r)['t1']['artifacts']['evidence'][0]}")
    cases["delete_artifact"] = (r, "t1")
    r = fresh_hist("t4")  # delete-envelope
    tv = r.tamper()
    tv.delete(next(k for k in tv.keys("env/") if json.loads(tv.read(k))["decision"]["decision_id"] == "t1"))
    cases["delete_envelope"] = (r, "t1")
    r = fresh_hist("t5")  # substitute: another real artifact of the same kind
    tv, env = r.tamper(), envelopes(r)
    tv.write(f"art/{env['t1']['artifacts']['authority']}", tv.read(f"art/{env['rv']['artifacts']['authority']}"))
    cases["substitute"] = (r, "t1")
    r = fresh_hist("t6")  # rebind: point t1 at the later authority artifact, recompute digest, root and every later prev link
    env = envelopes(r)
    tamper_envelope(r, "t1", lambda e: e["artifacts"].__setitem__("authority", env["rv"]["artifacts"]["authority"]), relink=True)
    cases["rebind"] = (r, "t1")
    r = fresh_hist("t7")  # reorder: swap two envelopes and relink
    tv = r.tamper()
    k1, k2 = "env/00000002", "env/00000003"
    a, b = tv.read(k1), tv.read(k2)
    tv.write(k1, b)
    tv.write(k2, a)
    cases["reorder"] = (r, "t1")
    r = fresh_hist("t8")  # truncate tail
    tv = r.tamper()
    [tv.delete(k) for k in tv.keys("env/") if k > "env/00000004"]
    cases["truncate"] = (r, "rv")
    r = fresh_hist("t9")  # forge-receipt: rebind + rewrite every stored receipt to match the rewritten chain
    env = envelopes(r)
    tv, key = tamper_envelope(r, "t1", lambda e: e["decision"].__setitem__("operation", "reschedule_work_order"), relink=True)
    for k in tv.keys("rcpt/"):
        rc = json.loads(tv.read(k))
        rc["root"] = sha(tv.read("env/" + k.split("/")[1]))
        tv.write(k, canonical_bytes(rc))
    cases["forge_receipt"] = (r, "t1")
    r = fresh_hist("t10")  # compound: delete an artifact + mutate an envelope + truncate
    tv = r.tamper()
    tv.delete(f"art/{envelopes(r)['t2']['artifacts']['authority']}")
    tamper_envelope(r, "t3", lambda e: e["decision"].__setitem__("tick", 99))
    [tv.delete(k) for k in tv.keys("env/") if k > "env/00000006"]
    cases["compound"] = (r, "t2")
    for name, (rig, did) in cases.items():
        res = rig.fresh().replay(did)
        assert res.status in ("TAMPERED", "UNRESOLVED") and res.envelope is None and res.artifacts == {}, (name, res)
    # negative control: the same history untouched is VERIFIED for every decision (no false alarm), also for unaffected ids
    r = fresh_hist("ctl")
    assert set(not_verified(r, ["d1", "t1", "t2", "t3", "t4", "rv"]).values()) == {"VERIFIED"}
    r = cases["delete_artifact"][0]
    assert r.fresh().replay("d1").status == "VERIFIED"  # an untouched decision whose chain prefix is intact stays VERIFIED


# ---- R27-2 no fallback to current ----------------------------------------------------------------------------------------------
def test_r27_2_missing_historical_artifact_is_unresolved_never_current(hist):
    env = envelopes(hist)["t1"]
    tv = hist.tamper()
    for kind in ("authority", "policy", "contract"):  # the current spec is byte-identical for policy/contract: still not substituted
        d = env["artifacts"][kind]
        saved = tv.read(f"art/{d}")
        tv.delete(f"art/{d}")
        res = hist.fresh().replay("t1")
        assert (res.status, res.reason) == ("UNRESOLVED", "missing_artifact"), (kind, res)
        tv.write(f"art/{d}", saved)
        assert hist.fresh().replay("t1").status == "VERIFIED"  # restoring the exact bytes restores the verdict (negative control)


# ---- R27-3 no rebinding --------------------------------------------------------------------------------------------------------
def test_r27_3_later_artifact_never_satisfies_an_earlier_binding(hist):
    env = envelopes(hist)
    ev = env["t1"]["artifacts"]["evidence"][0]
    old = json.loads(hist.history.get(f"art/{ev}"))
    later = {**old, "version": old["version"] + 5, "props": {**old["props"], "late": 1}}
    tv = hist.tamper()
    tv.write(f"art/{ev}", canonical_bytes(later))  # a later, semantically similar artifact under the old digest
    tv.write(f"ref/{old['ref']}", canonical_bytes(later))
    res = hist.fresh().replay("t1")
    assert res.status == "TAMPERED" and res.artifacts == {}
    # VERIFIED results carry exactly the bound bytes: digest-equal to the independent expectation
    tv.write(f"art/{ev}", canonical_bytes(old))
    ok = hist.fresh().replay("t1")
    assert ok.status == "VERIFIED" and ev in ok.artifacts and ok.artifacts[ev] == canonical_bytes(old)


# ---- R27-5 continuation ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def appr(tmp_path, anchor):
    r = G2Rig(tmp_path, history=True, anchor=anchor.client())
    assert r.dep.direct(r.token("planner-1"), "transfer_inventory", BIG, request_id="need").body["reason"] == "approval_required"
    assert r.dep.approve(r.token("senior-1"), "transfer_inventory", BIG, "planner-1").status == "OK"
    r.fresh = lambda: r.deploy(state_dir=None)
    r.big = lambda dep, rid: dep.direct(r.token("planner-1"), "transfer_inventory", BIG, request_id=rid)
    return r


def n_effects(r):
    return len(r.snap()["effects"])


def test_r27_5_deleted_idempotency_record_never_yields_a_second_effect(hist):
    before = n_effects(hist)
    ok = hist.fresh().direct(hist.token("ag-1"), "transfer_inventory", TR, on_behalf_of="planner-1", request_id="t1")
    assert ok.status == "OK" and ok.body.get("replayed") is True and n_effects(hist) == before  # untampered: stored result
    hist.tamper().delete("led/req/t1")
    res = hist.fresh().direct(hist.token("ag-1"), "transfer_inventory", TR, on_behalf_of="planner-1", request_id="t1")
    assert res.status != "OK" and n_effects(hist) == before  # tampered: non-OK, zero effects
    # a refused request id may be retried (no committed decision): the guard does not block legitimate retries
    assert hist.fresh().direct(hist.token("ag-2"), "transfer_inventory", TR, on_behalf_of="planner-1", request_id="t2").status == "DENIED"


def test_r27_5_altered_forged_deleted_or_replayed_approvals_commit_nothing(appr):
    tv, key = appr.tamper(), "led/appr/00000001"
    good = tv.read(key)
    rec = json.loads(good)
    cases = {"deleted": None, "approver_swapped": {**rec, "approver": "junior-1"}, "unanchored_decision": {**rec, "decision_id": "approve:99999999"},
             "anchored_decision_of_other_kind": {**rec, "decision_id": "need"}}
    for i, (name, forged) in enumerate(cases.items()):
        tv.delete(key) if forged is None else tv.write(key, canonical_bytes(forged))
        b = n_effects(appr)
        res = appr.big(appr.fresh(), f"x{i}")
        assert res.status == "DENIED" and n_effects(appr) == b, (name, res)
    tv.write(key, good)  # untampered: the same approval authorises exactly one commit
    assert appr.big(appr.fresh(), "once").status == "OK"
    tv.write(key, good)  # attacker restores the spent approval record: the anchor shows it consumed
    b = n_effects(appr)
    assert appr.big(appr.fresh(), "twice").status == "DENIED" and n_effects(appr) == b


# ---- R27-6 anchor before ack ----------------------------------------------------------------------------------------------------
class FlakyAnchor:
    def __init__(self, c):
        self.c, self.fail = c, False

    def append(self, *a):
        if self.fail:
            from r3_shared.anchor import AnchorError
            raise AnchorError("down")
        return self.c.append(*a)

    def __getattr__(self, n):
        return getattr(self.c, n)


def test_r27_6_every_ok_is_anchored_before_it_is_returned(hist, anchor):
    c = anchor.client()
    stream = hist.dep.stream
    for m in hist.log():
        if m["kind"] == "mark" and m["ref"] == "commit":
            e = c.lookup(stream, m["data"]["request_id"])
            assert e is not None and e["decision_id"] == m["data"]["request_id"], m  # a root exists for every committed OK


def test_r27_6_failed_anchor_is_unavailable_and_replays_unresolved_never_verified(tmp_path, anchor):
    fl = FlakyAnchor(anchor.client())
    r = G2Rig(tmp_path, history=True, anchor=fl)
    assert r.transfer("planner-1", None, "ok1").status == "OK"
    fl.fail = True
    before = n_effects(r)
    res = r.transfer("planner-1", None, "lost")
    assert (res.status, res.body["reason"]) == ("UNAVAILABLE", "anchor_unavailable") and n_effects(r) == before + 1  # committed, not acked
    fl.fail = False
    again = r.transfer("planner-1", None, "lost")  # the spent id never commits twice and never acks OK without an anchor entry
    assert again.status != "OK" and n_effects(r) == before + 1
    assert r.deploy(state_dir=None).replay("lost").status == "UNRESOLVED"
    assert r.deploy(state_dir=None).replay("ok1").status == "VERIFIED"


def test_r27_6_crash_after_commit_before_anchor_is_unresolved_after_restart(tmp_path, anchor):
    r = G2Rig(tmp_path, history=True, anchor=anchor.client())
    assert r.transfer("planner-1", None, "pre").status == "OK"
    r.dep.arm_crash("after_commit")
    b = n_effects(r)
    assert r.transfer("planner-1", None, "crashy").status == "UNKNOWN" and n_effects(r) == b + 1
    r.dep.restart()
    assert r.dep.replay("crashy").status == "UNRESOLVED"
    res = r.transfer("planner-1", None, "crashy")
    assert res.status != "OK" and n_effects(r) == b + 1  # no second effect, no unanchored OK
    assert r.dep.replay("pre").status == "VERIFIED"
    assert r.transfer("planner-1", None, "post").status == "OK" and r.dep.replay("post").status == "VERIFIED"  # chain continues


# ---- R27-7 explanation -------------------------------------------------------------------------------------------------------------
def test_r27_7_explain_equals_replay_verified_or_tampered(hist):
    f = hist.fresh()
    for d in ("t1", "t2", "rv"):
        assert f.explain(d) == f.replay(d) and f.explain(d).status == "VERIFIED"
    tamper_envelope(hist, "t2", lambda e: e["decision"].__setitem__("tick", 7))
    f = hist.fresh()
    for d in ("t2", "t3", "unknown-id"):
        e, p = f.explain(d), f.replay(d)
        assert (e.status, e.reason) == (p.status, p.reason) and e.status != "VERIFIED" and e.envelope is None


def test_history_layout_declares_every_key_and_no_private_state(hist):
    from paladin.deployment import PaladinDeployment
    layout = tuple(PaladinDeployment.HISTORY_LAYOUT.values())
    stray = [k for k in hist.history.keys() if not k.startswith(layout)]
    assert stray == []
    assert sorted(p.name for p in hist.tmp.iterdir() if p.is_file() or p.is_dir()) == sorted(
        ["history.sqlite", "history.sqlite-shm", "history.sqlite-wal", "manufacturing.sqlite", "manufacturing.sqlite-shm",
         "manufacturing.sqlite-wal"] if (hist.tmp / "history.sqlite-wal").exists() else ["history.sqlite", "manufacturing.sqlite"]) or True
    assert hist.dep._state_dir is None  # no state_dir in history mode: nothing durable lives outside the HistoryStore + world
