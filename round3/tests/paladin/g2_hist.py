"""H27 test helpers: a base history, independent expectations (hand-derived from the frozen spec text), tamper primitives."""
from __future__ import annotations

import hashlib
import json

from g2_rig import TR, edge
from r3_shared.evidence import canonical_bytes

BIG = {**TR, "quantity": 400}


def sha(x) -> str:
    return hashlib.sha256(x if isinstance(x, bytes) else canonical_bytes(x)).hexdigest()


def build(r):
    """7 decisions (OK, edge OK, edge refusal, approval-required refusal, approve, approved OK, revoke). Returns ids + snapshots."""
    snaps, ids = {}, {}

    def step(name, fn):
        snaps[name] = r.snap()
        res = fn()
        ids[name] = name
        return res
    assert step("d1", lambda: r.delegate("planner-1", edge("e1", "planner-1", "ag-1"), "d1")).status == "OK"
    assert step("t1", lambda: r.transfer("ag-1", "planner-1", "t1")).status == "OK"
    assert step("t2", lambda: r.transfer("ag-2", "planner-1", "t2")).status == "DENIED"
    assert step("t3", lambda: r.transfer("planner-1", None, "t3", BIG)).body["reason"] == "approval_required"
    assert step("ap", lambda: r.dep.approve(r.token("senior-1"), "transfer_inventory", BIG, "planner-1")).status == "OK"
    assert step("t4", lambda: r.transfer("planner-1", None, "t4", BIG)).status == "OK"
    assert step("rv", lambda: r.revoke("planner-1", "e1", "rv")).status == "OK"
    return snaps


def envelopes(r) -> dict:
    out = {}
    for k in r.history.keys("env/"):
        e = json.loads(r.history.get(k))
        out[e["decision"]["decision_id"]] = e
    return out


def expected_policy(ops, op):
    o = next(x for x in ops["operations"] if x["name"] == op)
    return {"config": ops["config"], "business_rules": o["business_rules"], "approval": o["approval"]}


def expected_contract(ops, op):
    o = next(x for x in ops["operations"] if x["name"] == op)
    return {**{k: v for k, v in o.items() if k not in ("business_rules", "approval")}, "helpers": ops["helpers"], "spec": ops["spec"]}


def expected_evidence(snap, refs):
    return sorted({sha({"ref": r, "version": snap["objects"][r]["version"], "props": snap["objects"][r]["props"]}) for r in refs})


def tamper_envelope(r, did, mutate, relink=False):
    """Rewrite one stored envelope through the TamperView; optionally recompute its digest-chain tail (a rebind attempt)."""
    tv = r.tamper()
    key = next(k for k in tv.keys("env/") if json.loads(tv.read(k))["decision"]["decision_id"] == did)
    e = json.loads(tv.read(key))
    mutate(e)
    tv.write(key, canonical_bytes(e))
    if relink:
        prev = sha(canonical_bytes(e))
        for k in [x for x in tv.keys("env/") if x > key]:
            nxt = json.loads(tv.read(k))
            nxt["prev"] = prev
            tv.write(k, canonical_bytes(nxt))
            prev = sha(canonical_bytes(nxt))
    return tv, key
