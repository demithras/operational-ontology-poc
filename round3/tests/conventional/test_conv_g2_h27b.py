"""PROT-H27 R27-5 (continuation), R27-6 (anchor before ack) and the four H27 mutants (conventional)."""
import json

import pytest

from conv_g2_util import make_g2, populate27, sha, tamper
from conventional.store import fingerprint
from r3_shared.anchor import AnchorError
from r3_shared.evidence import canonical_bytes
from r3_shared.world import diff

BIG = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 100}


class Flaky:
    """An AnchorClient whose append can be made to fail (the real anchor stays up for verification)."""

    def __init__(self, real):
        self.real, self.fail, self.appends = real, False, []

    def append(self, stream, seq, decision_id, root):
        if self.fail:
            raise AnchorError("anchor unreachable (test)")
        self.appends.append(decision_id)
        return self.real.append(stream, seq, decision_id, root)

    def __getattr__(self, n):
        return getattr(self.real, n)


def build(tmp_path, mutants=(), populate=True):
    r = make_g2(tmp_path, mutants=mutants, with_history=True)
    if populate:
        r.ids, r.results = populate27(r)
    stream = r.history.get("meta/stream").decode()
    r.stream = stream
    r.envs = {i: json.loads(r.history.get(f"env/{r.anchor.lookup(stream, i)['seq']:010d}")) for i in getattr(r, "ids", [])}
    return r


@pytest.fixture
def rig(tmp_path):
    r = build(tmp_path)
    yield r
    r.close()


def ledger_key(rid):
    return "ledger/" + sha(rid.encode())


# ---- R27-5 continuation -----------------------------------------------------------------------------------------
def test_r27_5_untampered_retry_returns_the_stored_result_with_zero_new_effects(rig):
    before = rig.snap()
    again = rig.redeploy().direct(rig.token("planner-1"), "transfer_inventory",
                                  {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 2},
                                  None, "x2")
    assert again.status == "OK" and again.body["request_id"] == "x2" and diff(before, rig.snap()) == []


@pytest.mark.parametrize("attack", ["delete", "garbage", "rewrite_fp"])
def test_r27_5_tampered_idempotency_record_never_yields_a_second_effect(rig, attack):
    t, key = tamper(rig), ledger_key("x2")
    raw = rig.history.get(key)
    {"delete": lambda: t.delete(key), "garbage": lambda: t.write(key, b"\x00not json"),
     "rewrite_fp": lambda: t.write(key, canonical_bytes({**json.loads(raw), "fp": "0" * 64}))}[attack]()
    before = rig.snap()
    r = rig.redeploy().direct(rig.token("planner-1"), "transfer_inventory",
                              {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 2},
                              None, "x2")
    assert r.status != "OK", r
    assert diff(before, rig.snap()) == []
    assert len([m for m in rig.marks("commit") if m["data"]["request_id"] == "x2"]) == 1


def test_r27_5_stored_approval_is_bound_to_the_world_log_not_to_a_forgeable_record(tmp_path):
    r = build(tmp_path, populate=False)
    try:
        h = r.store.handle("seed")
        h.update("InventoryLot", "LOT-B-PX17", {"onHand": 400})
        h.update("EvidenceSnapshot", "ES-1", {"snapshotObservedAt": 1})
        h.close()
        fp = fingerprint("planner-1", None, "transfer_inventory", BIG)
        t = tamper(r)
        t.write("approval/0000009999", canonical_bytes({"fp": fp, "approver": "senior-1", "seq": 9999}))  # forged
        before = r.snap()
        req = lambda rid: r.dep.direct(r.token("planner-1"), "transfer_inventory", BIG, None, rid)  # noqa: E731
        no = req("a1")
        assert (no.status, no.body["reason"]) == ("DENIED", "approval_required") and diff(before, r.snap()) == []
        assert r.dep.approve(r.token("senior-1"), "transfer_inventory", BIG, "planner-1").status == "OK"
        (key,) = [k for k in r.history.keys("approval/") if k != "approval/0000009999"]
        t.delete(key)  # the stored copy of a REAL approval is deleted
        before = r.snap()
        res = req("a2")
        assert res.status != "OK" and diff(before, r.snap()) == []
        t.write(key, json.dumps({"fp": fp, "approver": "senior-1", "seq": 1}).encode())  # a rewritten one (wrong seq/bytes)
        assert req("a3").status != "OK" and diff(before, r.snap()) == []
    finally:
        r.close()


def test_r27_5_untampered_approval_commits_once_then_is_consumed(tmp_path):
    r = build(tmp_path, populate=False)
    try:
        h = r.store.handle("seed")
        h.update("InventoryLot", "LOT-B-PX17", {"onHand": 400})
        h.update("EvidenceSnapshot", "ES-1", {"snapshotObservedAt": 1})
        h.close()
        assert r.dep.approve(r.token("senior-1"), "transfer_inventory", BIG, "planner-1").status == "OK"
        assert r.dep.direct(r.token("planner-1"), "transfer_inventory", BIG, None, "a1").status == "OK"
        assert r.dep.direct(r.token("planner-1"), "transfer_inventory", BIG, None, "a2").body["reason"] == "approval_required"
        assert r.redeploy().replay("a1").status == "VERIFIED"
        assert [m["data"] for m in r.marks("approval_used")] and len(r.marks("approval")) == 1
    finally:
        r.close()


# ---- R27-6 anchor before ack ------------------------------------------------------------------------------------
def test_r27_6_every_ok_in_the_world_log_has_an_anchor_entry(rig):
    ids = [m["data"]["request_id"] for m in rig.marks("commit")]
    assert ids and all(rig.anchor.lookup(rig.stream, i) is not None for i in ids)


def test_r27_6_an_anchor_failure_withholds_the_result_and_replay_says_unanchored(tmp_path):
    r = build(tmp_path, populate=False)
    try:
        flaky = Flaky(r.anchor)
        dep = r.variant.deploy("manufacturing", r.store.handle_factory(), r.idp.verifier(), r.ops, r.auth, r.clock, None,
                               r.history, flaky)
        args = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 2}
        h = r.store.handle("seed")
        h.update("EvidenceSnapshot", "ES-1", {"snapshotObservedAt": 1})
        h.close()
        flaky.fail = True
        res = dep.direct(r.token("planner-1"), "transfer_inventory", args, None, "u1")
        assert (res.status, res.body["reason"]) == ("UNAVAILABLE", "anchor_unavailable")
        assert [m for m in r.marks("commit") if m["data"]["request_id"] == "u1"]  # the world tx did commit
        flaky.fail = False
        retry = dep.direct(r.token("planner-1"), "transfer_inventory", args, None, "u1")
        assert retry.status != "OK" and retry.body["reason"] == "anchor_unavailable"  # never OK without an anchor entry
        assert len([m for m in r.marks("commit") if m["data"]["request_id"] == "u1"]) == 1
        rr = r.redeploy().replay("u1")
        assert (rr.status, rr.reason) == ("UNRESOLVED", "unanchored")
    finally:
        r.close()


def test_r27_6_crash_after_commit_before_anchor_is_unresolved_never_verified(rig):
    args = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 1}
    rig.dep.arm_crash("after_commit")
    assert rig.dep.direct(rig.token("planner-1"), "transfer_inventory", args, None, "c1").status == "UNKNOWN"
    rig.dep.restart()
    assert rig.redeploy().replay("c1").status == "UNRESOLVED"
    again = rig.dep.direct(rig.token("planner-1"), "transfer_inventory", args, None, "c1")
    assert again.status != "OK" and len([m for m in rig.marks("commit") if m["data"]["request_id"] == "c1"]) == 1
    nxt = rig.dep.direct(rig.token("planner-1"), "transfer_inventory", {**args, "quantity": 2}, None, "c2")  # chain continues
    assert nxt.status == "OK" and rig.redeploy().replay("c2").status == "VERIFIED"


# ---- the four H27 mutants: each makes a tamper VERIFIED that the correct build flags ---------------------------------
def attack_policy(r):
    stream_seq = r.envs["x4"]["seq"]
    side = r.history.get(f"side/{stream_seq:010d}")  # only the digest_omission mutant keeps one
    d = side.decode() if side else r.envs["x4"]["artifacts"]["policy"]
    new = json.loads(r.history.get(f"art/{d}"))
    new["config"]["approval_threshold_units"] = 1  # a weakened historical policy
    nb, t = canonical_bytes(new), tamper(r)
    if side:
        t.write(f"art/{sha(nb)}", nb)
        t.write(f"side/{stream_seq:010d}", sha(nb).encode())
    else:
        t.write(f"art/{d}", nb)


def attack_delete_policy(r):
    tamper(r).delete(f"art/{r.envs['x4']['artifacts']['policy']}")  # the CURRENT ops spec yields byte-identical bytes


def attack_rewrite_evidence_in_place(r):
    d = next(d for d in r.envs["x1"]["artifacts"]["evidence"] if json.loads(r.history.get(f"art/{d}"))["ref"] == "EvidenceSnapshot:ES-1")
    e = json.loads(r.history.get(f"art/{d}"))
    e["props"]["snapshotObservedAt"] = 999
    tamper(r).write(f"art/{d}", canonical_bytes(e))


def attack_forge_receipts(r):
    t, k = tamper(r), f"env/{r.envs['x1']['seq']:010d}"
    e = json.loads(r.history.get(k))
    e["decision"]["status"] = "DENIED"
    t.write(k, canonical_bytes(e))
    prev = sha(canonical_bytes(e))
    for k2 in r.history.keys("env/")[r.envs["x1"]["seq"]:]:
        e2 = json.loads(r.history.get(k2))
        e2["prev"] = prev
        t.write(k2, canonical_bytes(e2))
        prev = sha(canonical_bytes(e2))
    for k3 in r.history.keys("env/"):
        n = k3.split("/")[1]
        t.write(f"receipt/{n}", canonical_bytes({**json.loads(r.history.get(f"receipt/{n}")), "root": sha(r.history.get(k3))}))


MUTANTS = [("digest_omission", attack_policy, "x4"), ("fallback_to_current", attack_delete_policy, "x4"),
           ("evidence_rebinding", attack_rewrite_evidence_in_place, "x1"), ("receipt_self_trust", attack_forge_receipts, "x1")]


@pytest.mark.parametrize("mutant,attack,rid", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_h27_mutant_is_killed_by_its_tamper_and_the_correct_build_is_not_fooled(tmp_path, mutant, attack, rid):
    for name, mutants in (("correct", []), ("mutant", [mutant])):
        d = tmp_path / name
        d.mkdir()
        r = build(d, mutants)
        try:
            assert r.redeploy().replay(rid).status == "VERIFIED"  # clean control
            attack(r)
            st = r.redeploy().replay(rid).status
            assert (st == "VERIFIED") is (name == "mutant"), f"{name}: {st}"
        finally:
            r.close()
