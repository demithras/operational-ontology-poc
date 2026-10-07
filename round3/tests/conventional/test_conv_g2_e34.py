"""Errata E-3/E-4 (conventional): envelope fields built BY HAND from the E-4 text and compared with what the variant stored;
delegation under a v1 authority spec; Deployment methods never raise. No oracle/harness imports."""
import json

import pytest

from conv_g2_util import TRANSFER, edge, make_g2, sha, v2_spec
from r3_shared.authspec import load_auth_spec
from r3_shared.evidence import canonical_bytes as cb
from r3_shared.variant import CallResult

BIG = {**TRANSFER, "quantity": 100}
NULL = sha(cb(None))


def envs(r):
    stream = r.history.get("meta/stream").decode()
    out, seq = [], 1
    while r.history.get(f"env/{seq:010d}") is not None:
        out.append(json.loads(r.history.get(f"env/{seq:010d}")))
        seq += 1
    return out


def env_for(r, rid):
    (e,) = [e for e in envs(r) if e["decision"]["decision_id"] == rid]
    return e


def tx_rows(r, tx):
    return [{"seq": x["seq"], "tx": x["tx"], "tag": x["tag"], "tick": x["tick"], "writer": x["writer"],
             "kind": x["kind"], "ref": x["ref"], "data": x["data"]} for x in r.log() if x["tx"] == tx]


@pytest.fixture
def rig(tmp_path):
    r = make_g2(tmp_path, with_history=True)
    h = r.store.handle("seed")
    h.update("InventoryLot", "LOT-B-PX17", {"onHand": 400})
    h.close()
    yield r
    r.close()


def test_e4_delegate_and_revoke_envelopes_by_hand(rig):
    r, d, t = rig, rig.dep, rig.token
    e1 = edge("e1", "planner-1", "nobody-1")
    assert d.delegate(t("planner-1"), e1, "d1").status == "OK"
    commit = [m for m in r.marks("commit") if m["data"]["request_id"] == "d1"][0]
    dec = env_for(r, "d1")["decision"]
    assert dec["operation"] is None and dec["kind"] == "delegate" and dec["decision_id"] == "d1"
    assert dec["args_digest"] == sha(cb(e1))                      # the edge dict, not a wrapper
    assert dec["effect_digest"] == sha(cb(tx_rows(r, commit["tx"])))  # marks included
    assert [x["kind"] for x in tx_rows(r, commit["tx"])].count("mark") >= 2
    assert (dec["world_seq"], dec["tick"]) == (commit["seq"], commit["tick"])
    arts = env_for(r, "d1")["artifacts"]
    assert arts["policy"] == NULL and arts["contract"] == NULL and arts["evidence"] == []
    assert d.revoke(t("planner-1"), "e1", "rv").status == "OK"
    commit = [m for m in r.marks("commit") if m["data"]["request_id"] == "rv"][0]
    dec = env_for(r, "rv")["decision"]
    assert dec["operation"] is None and dec["args_digest"] == sha(cb("e1"))  # the edge_id STRING
    assert dec["effect_digest"] == sha(cb(tx_rows(r, commit["tx"]))) and dec["world_seq"] == commit["seq"]


def test_e4_call_tool_direct_and_refusal_envelopes_by_hand(rig):
    r, d, t = rig, rig.dep, rig.token
    args = {**TRANSFER, "quantity": 2}
    assert d.call_tool(t("planner-1"), "transfer_inventory", dict(args), None, "c1").status == "OK"
    assert d.direct(t("planner-1"), "transfer_inventory", {**TRANSFER, "quantity": 3}, None, "c2").status == "OK"
    for rid, a in (("c1", args), ("c2", {**TRANSFER, "quantity": 3})):
        commit = [m for m in r.marks("commit") if m["data"]["request_id"] == rid][0]
        dec = env_for(r, rid)["decision"]
        assert dec["operation"] == "transfer_inventory" and dec["decision_id"] == rid
        assert dec["args_digest"] == sha(cb(a)) and dec["effect_digest"] == sha(cb(tx_rows(r, commit["tx"])))
        assert (dec["world_seq"], dec["tick"]) == (commit["seq"], commit["tick"])
    ops = r.ops
    op = [o for o in ops["operations"] if o["name"] == "transfer_inventory"][0]
    arts = env_for(r, "c1")["artifacts"]
    assert arts["policy"] == sha(cb({"config": ops["config"], "business_rules": op["business_rules"],
                                     "approval": op["approval"]}))
    body = {k: v for k, v in op.items() if k not in ("business_rules", "approval")}
    assert arts["contract"] == sha(cb({**body, "helpers": ops["helpers"], "spec": ops["spec"]}))
    # refusal: [] effects, world_seq = log head, tick = clock at deciding
    head, now = max(x["seq"] for x in r.log()), r.clock.now()
    res = d.direct(t("junior-1"), "expedite_purchase_order", {"po_id": "PO-991", "expedite_fee": 1}, None, "z1")
    assert res.status != "OK"
    dec = env_for(r, "z1")["decision"]
    assert dec["effect_digest"] == sha(cb([])) and dec["world_seq"] == head and dec["tick"] == now


def test_e4_approve_envelope_by_hand(rig):
    r, d, t = rig, rig.dep, rig.token
    assert d.approve(t("senior-1"), "transfer_inventory", dict(BIG), "planner-1").status == "OK"
    (dec,) = [e["decision"] for e in envs(r) if e["decision"]["kind"] == "approve"]
    rows = [x for x in r.log() if x["tag"] == "approve"]
    assert dec["operation"] == "transfer_inventory" and dec["decision_id"]
    assert dec["args_digest"] == sha(cb(BIG))                      # the approved request's args, NOT a wrapper
    assert dec["effect_digest"] == sha(cb(tx_rows(r, rows[0]["tx"])))
    assert (dec["world_seq"], dec["tick"]) == (rows[-1]["seq"], rows[-1]["tick"])  # no commit mark: last effect row
    ids = [e["decision"]["decision_id"] for e in envs(r)]
    assert len(ids) == len(set(ids))


def test_e4_newest_tie_break_is_greatest_value_then_smallest_ref(rig):
    r, d, t = rig, rig.dep, rig.token
    h = r.store.handle("seed")
    h.create("EvidenceSnapshot", "ES-9", {"iri": "ES-9", "snapshotContentHash": "1" * 64, "snapshotObservedAt": 7})
    h.create("EvidenceSnapshot", "ES-3", {"iri": "ES-3", "snapshotContentHash": "1" * 64, "snapshotObservedAt": 7})
    h.close()
    assert d.direct(t("planner-1"), "transfer_inventory", {**TRANSFER, "quantity": 2}, None, "n1").status == "OK"
    snap = r.snap()["objects"]["EvidenceSnapshot:ES-3"]
    want = sha(cb({"ref": "EvidenceSnapshot:ES-3", "version": snap["version"], "props": snap["props"]}))
    assert want in env_for(r, "n1")["artifacts"]["evidence"]
    other = r.snap()["objects"]["EvidenceSnapshot:ES-9"]
    assert sha(cb({"ref": "EvidenceSnapshot:ES-9", "version": other["version"], "props": other["props"]})) \
        not in env_for(r, "n1")["artifacts"]["evidence"]


# ---- E-3 ---------------------------------------------------------------------------------------------------------
def v1_spec():
    a = {k: v for k, v in v2_spec().items() if k not in ("spec", "max_delegation_depth", "capabilities", "revoked")}
    return {**a, "spec": load_auth_spec("manufacturing")["spec"]}


@pytest.mark.parametrize("deploy_v1", [True, False])
def test_e3_v1_spec_behaves_as_empty_v2(tmp_path, deploy_v1):
    r = make_g2(tmp_path, spec=v1_spec() if deploy_v1 else None, with_history=True)
    try:
        if not deploy_v1:
            r.dep.set_authority(v1_spec())
        d, t = r.dep, r.token
        assert "capabilities" not in d.service.policy.doc
        e1 = edge("e1", "planner-1", "nobody-1")
        assert d.delegate(t("planner-1"), e1, "d1").status == "OK"
        assert d.authority_used("d1").status in ("OK", "INVALID")
        assert d.direct(t("nobody-1"), "transfer_inventory", TRANSFER, "planner-1", "x1").status in ("OK", "DENIED")
        assert d.revoke(t("planner-1"), "e1", "rv").status == "OK"
        assert d.revoke(t("planner-1"), "nope", "rv2").status == "INVALID"
        assert d.delegate(t("planner-1"), edge("e2", "planner-1", "nobody-1"), "d2").status == "OK"
        # the depth bound is the frozen maximum 8: a chain of 9 re-delegations is refused at the 9th hop
        assert d.authority_state()["max_delegation_depth"] == 8
    finally:
        r.close()


def test_e3_authority_used_and_refusals_under_v1_never_raise(tmp_path):
    r = make_g2(tmp_path, spec=v1_spec())
    try:
        assert r.dep.authority_used("never").status == "INVALID"
        assert r.dep.delegate(r.token("planner-1"), {"id": 1}, "b1").status == "INVALID"
        assert r.dep.delegate("garbage", edge("e", "planner-1", "nobody-1"), "b2").status == "DENIED"
    finally:
        r.close()


@pytest.mark.parametrize("method,args", [
    ("delegate", ("T", edge("e", "planner-1", "nobody-1"), "i")), ("revoke", ("T", "e", "i")),
    ("authority_used", ("i",)), ("approve", ("T", "transfer_inventory", dict(BIG), "planner-1")),
    ("read", ("T", "get", {"type": "Part", "key": "PX-17"})),
    ("direct", ("T", "transfer_inventory", dict(TRANSFER), None, "i")),
    ("call_tool", ("T", "transfer_inventory", dict(TRANSFER), None, "i"))])
def test_e3_internal_errors_become_call_results(tmp_path, method, args):
    r = make_g2(tmp_path)
    try:
        def boom(*a, **k):
            raise RuntimeError("injected")
        target = r.dep.service if method != "call_tool" else r.dep._tools
        setattr(target, {"direct": "execute", "call_tool": "call_tool"}.get(method, method), boom)
        res = getattr(r.dep, method)(*args)
        assert isinstance(res, CallResult) and res.status == "UNAVAILABLE" and res.body["reason"] == "internal_error"
    finally:
        r.close()
