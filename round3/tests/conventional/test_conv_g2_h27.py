"""PROT-H27 R27-1..4 and R27-7 (conventional). Hand-written expectations; tampering only through the TamperView
primitives (keys/read/write/delete/rename). Replay always runs on a FRESH deployment (empty state)."""
import json

import pytest

from conv_g2_util import make_g2, populate27, sha, tamper
from r3_shared.evidence import canonical_bytes


@pytest.fixture
def rig(tmp_path):
    r = make_g2(tmp_path, with_history=True)
    r.ids, r.results = populate27(r)
    r.envs = {i: json.loads(r.history.get(f"env/{r.anchor.lookup(json.loads(r.history.get('meta/stream').decode()) if False else r.history.get('meta/stream').decode(), i)['seq']:010d}")) for i in r.ids}
    yield r
    r.close()


def env_of(r, rid):
    return r.envs[rid]  # pristine envelopes captured before any tampering


def statuses(r, ids=None):
    f = r.redeploy()
    return {i: f.replay(i).status for i in (ids or r.ids)}


# ---- R27-4 clean histories ---------------------------------------------------------------------------------------
def test_r27_4_clean_history_replays_every_decision_as_verified(rig):
    assert all(x.status in ("OK", "DENIED", "INVALID") for x in rig.results)
    assert statuses(rig) == {i: "VERIFIED" for i in rig.ids}


def test_r27_4_bound_artifacts_are_exactly_the_frozen_evidence_set(rig):
    res = rig.redeploy().replay("x1")  # edge request: transfer WH-B -> WH-A, PX-17; newest EvidenceSnapshot term
    assert res.status == "VERIFIED"
    refs = {json.loads(b)["ref"]: json.loads(b) for d, b in res.artifacts.items() if "ref" in json.loads(b)}
    assert set(refs) == {"Warehouse:WH-A", "Warehouse:WH-B", "Part:PX-17", "EvidenceSnapshot:ES-1"}
    assert refs["EvidenceSnapshot:ES-1"]["props"]["snapshotObservedAt"] == 1
    d = res.envelope["decision"]
    assert (d["kind"], d["status"], d["subject"], d["on_behalf_of"], d["authority_path"]) == \
        ("direct", "OK", "nobody-1", "planner-1", ["e1"])
    assert sorted(res.envelope["artifacts"]["evidence"]) == res.envelope["artifacts"]["evidence"]
    assert set(res.envelope) == {"v", "stream", "seq", "prev", "decision", "artifacts"}
    assert set(res.envelope["artifacts"]) == {"evidence", "authority", "policy", "contract"}
    for dig, b in res.artifacts.items():
        assert sha(b) == dig


def test_r27_4_decision_scalars_match_the_world_log(rig):
    for rid in ("x1", "x2", "x4"):
        e = rig.redeploy().replay(rid).envelope
        commit = next(m for m in rig.marks("commit") if m["data"]["request_id"] == rid)
        assert e["decision"]["world_seq"] == commit["seq"] and e["decision"]["tick"] == commit["tick"]
        rows = [r for r in rig.log() if r["tx"] == commit["tx"]]
        assert e["decision"]["effect_digest"] == sha(canonical_bytes(rows))
    assert env_of(rig, "x2")["decision"]["kind"] == "call_tool"
    refused = env_of(rig, "x3")["decision"]  # authority refusal: no world transaction, world_seq = log head when deciding
    assert (refused["status"], refused["effect_digest"]) == ("DENIED", sha(canonical_bytes([])))
    assert env_of(rig, "x5")["decision"]["reason"] == "no_valid_path"  # the request through the revoked edge
    assert env_of(rig, "d1")["artifacts"]["evidence"] == []  # delegate binds no evidence


def test_r27_4_chain_is_gap_free_and_prev_linked(rig):
    envs = [json.loads(rig.history.get(k)) for k in rig.history.keys("env/")]
    assert [e["seq"] for e in envs] == list(range(1, len(rig.ids) + 1))
    for a, b in zip(envs, envs[1:]):
        assert b["prev"] == sha(canonical_bytes(a))
    assert envs[0]["prev"] == "0" * 64
    assert rig.redeploy().replay("nope").reason == "unknown_decision"


# ---- R27-1 detection: every mutation class -> never VERIFIED ---------------------------------------------------
def seq_key(r, rid):
    return f"env/{r.envs[rid]['seq']:010d}"


def relink(r, t, start=1):
    """Recompute prev links, anchor-free: what a forging attacker does after editing an envelope."""
    keys = r.history.keys("env/")
    prev = "0" * 64 if start == 1 else sha(r.history.get(keys[start - 2]))
    for k in keys[start - 1:]:
        e = json.loads(r.history.get(k))
        e["prev"] = prev
        t.write(k, canonical_bytes(e))
        prev = sha(canonical_bytes(e))


def mut_field(r, t):
    k = seq_key(r, "x1")
    e = json.loads(r.history.get(k))
    e["decision"]["status"] = "DENIED"
    t.write(k, canonical_bytes(e))


def mut_artifact(r, t):
    d = env_of(r, "x1")["artifacts"]["authority"]
    t.write(f"art/{d}", r.history.get(f"art/{d}") + b" ")


def del_artifact(r, t):
    t.delete(f"art/{env_of(r, 'x4')['artifacts']['evidence'][0]}")


def del_envelope(r, t):
    t.delete(seq_key(r, "x2"))


def substitute(r, t):
    a, b = env_of(r, "x1")["artifacts"]["authority"], env_of(r, "rv")["artifacts"]["authority"]
    assert a != b
    t.write(f"art/{a}", r.history.get(f"art/{b}"))


def rebind(r, t):
    k, e = seq_key(r, "x1"), json.loads(r.history.get(seq_key(r, "x1")))
    e["artifacts"]["authority"] = env_of(r, "rv")["artifacts"]["authority"]
    t.write(k, canonical_bytes(e))
    relink(r, t)


def reorder(r, t):
    k1, k2 = seq_key(r, "x1"), seq_key(r, "x2")
    a, b = r.history.get(k1), r.history.get(k2)
    t.write(k1, b)
    t.write(k2, a)
    relink(r, t)


def truncate(r, t):
    for k in r.history.keys("env/")[-2:]:
        t.delete(k)


def forge_receipts(r, t):
    mut_field(r, t)
    relink(r, t)
    for k in r.history.keys("env/"):
        n = k.split("/")[1]
        t.write(f"receipt/{n}", canonical_bytes({**json.loads(r.history.get(f"receipt/{n}")), "root": sha(r.history.get(k))}))


def compound(r, t):
    mut_artifact(r, t)
    del_envelope(r, t)


CLASSES = [mut_field, mut_artifact, del_artifact, del_envelope, substitute, rebind, reorder, truncate, forge_receipts,
           compound]


@pytest.mark.parametrize("cls", CLASSES, ids=lambda f: f.__name__)
def test_r27_1_every_mutation_class_is_detected_never_verified(rig, cls):
    t = tamper(rig)
    cls(rig, t)
    after = statuses(rig)
    assert any(s != "VERIFIED" for s in after.values()), f"{cls.__name__}: tampering went unnoticed {after}"
    assert t.log(), "the class applied no tamper primitive"


def test_r27_1_each_class_flags_the_decisions_it_touches(rig):
    t = tamper(rig)
    mut_field(rig, t)  # an edited envelope root no longer matches the anchor: x1 and every LATER link are affected
    s = statuses(rig)
    assert s["x1"] == "TAMPERED" and s["x2"] == "TAMPERED" and s["d1"] == "VERIFIED"  # earlier decisions stay VERIFIED


def test_r27_1_a_deleted_artifact_makes_that_decision_unresolved_and_leaves_unrelated_ones_verified(rig):
    del_artifact(rig, tamper(rig))
    s = statuses(rig)
    # content addressing: a blob shared with another decision's evidence (an unchanged Warehouse) is gone for both
    assert s["x4"] == "UNRESOLVED" and s["d1"] == "VERIFIED" and s["rv"] == "VERIFIED"


# ---- R27-2 no fallback to current -------------------------------------------------------------------------------
def test_r27_2_missing_authority_artifact_is_unresolved_even_if_current_spec_is_byte_identical(rig):
    dep = rig.redeploy()
    cur = canonical_bytes(dep.authority_state())  # the spec in force NOW (after the revoke)
    d = env_of(rig, "x5")["artifacts"]["authority"]
    assert sha(cur) == d  # identical bytes: a fallback-to-current implementation would pass
    tamper(rig).delete(f"art/{d}")
    r = rig.redeploy().replay("x5")
    assert (r.status, r.reason) == ("UNRESOLVED", "missing_artifact") and r.envelope is None


def test_r27_2_missing_policy_and_contract_artifacts_are_unresolved(rig):
    for kind in ("policy", "contract"):
        d = env_of(rig, "x4")["artifacts"][kind]
        t = tamper(rig)
        blob = rig.history.get(f"art/{d}")
        t.delete(f"art/{d}")
        assert rig.redeploy().replay("x4").reason == "missing_artifact"
        t.write(f"art/{d}", blob)
    assert rig.redeploy().replay("x4").status == "VERIFIED"  # restoring the bytes heals it: nothing else was touched


# ---- R27-3 no rebinding -----------------------------------------------------------------------------------------
def test_r27_3_verified_returns_the_version_bound_at_decision_time(rig):
    def es(res):
        return next(json.loads(b) for b in res.artifacts.values() if json.loads(b).get("ref") == "EvidenceSnapshot:ES-1")
    r1, r4 = rig.redeploy().replay("x1"), rig.redeploy().replay("x4")
    assert (es(r1)["props"]["snapshotObservedAt"], es(r4)["props"]["snapshotObservedAt"]) == (1, 2)
    assert es(r4)["version"] > es(r1)["version"]  # a newer version existed when x4 was decided
    pick = lambda rid: next(d for d in rig.envs[rid]["artifacts"]["evidence"]  # noqa: E731
                            if json.loads(rig.history.get(f"art/{d}"))["ref"] == "EvidenceSnapshot:ES-1")
    t = tamper(rig)
    t.write(f"art/{pick('x1')}", rig.history.get(f"art/{pick('x4')}"))  # a LATER similar artifact stands in for the old one
    assert rig.redeploy().replay("x1").status == "TAMPERED"
    assert rig.redeploy().replay("x4").status == "VERIFIED"


# ---- R27-7 explanation ------------------------------------------------------------------------------------------
def test_r27_7_explain_equals_replay_clean_and_tampered(rig):
    f = rig.redeploy()
    assert f.explain("x1") == f.replay("x1")
    t = tamper(rig)
    mut_field(rig, t)
    del_artifact(rig, t)
    f = rig.redeploy()
    for rid in rig.ids:
        a, b = f.explain(rid), f.replay(rid)
        assert (a.status, a.reason, a.envelope) == (b.status, b.reason, b.envelope)
    assert f.explain("x1").status == "TAMPERED" and f.explain("x4").status == "TAMPERED"  # chain break dominates
    assert f.explain("d1").status == "VERIFIED"
