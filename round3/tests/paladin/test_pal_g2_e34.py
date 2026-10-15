"""Errata E-3 / E-4 (Gate 2): envelope fields built BY HAND from the E-4 text and compared with what the variant stored;
delegation under a v1 authority spec; every Deployment method total (no uncaught exception)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g2_hist import BIG, envelopes, sha  # noqa: E402
from g2_rig import TR, G2Rig, edge, new_anchor  # noqa: E402
from r3_shared.authspec import load_auth_spec  # noqa: E402


@pytest.fixture(scope="module")
def anchor(tmp_path_factory):
    ap = new_anchor(tmp_path_factory.mktemp("anchor"))
    yield ap
    ap.close()


def tx_log(r, row):
    return [x for x in r.log() if x["tx"] == row["tx"]]


def commit_mark(r, rid):
    return next(m for m in r.log() if m["kind"] == "mark" and m["ref"] == "commit" and m["data"]["request_id"] == rid)


def test_e4_envelope_fields_by_hand(tmp_path, anchor):
    r = G2Rig(tmp_path, history=True, anchor=anchor.client())
    e1 = edge("e1", "planner-1", "ag-1")
    assert r.delegate("planner-1", e1, "d1").status == "OK"
    assert r.transfer("ag-1", "planner-1", "t1").status == "OK"
    head, tick = r.log()[-1]["seq"], r.clock.now()
    assert r.transfer("ag-2", "planner-1", "t2").status == "DENIED"
    refusal_head, refusal_tick = r.log()[-1]["seq"], r.clock.now()
    assert refusal_head == head
    head, tick = r.log()[-1]["seq"], r.clock.now()
    assert r.dep.approve(r.token("senior-1"), "transfer_inventory", BIG, "planner-1").status == "OK"
    assert r.revoke("planner-1", "e1", "rv").status == "OK"
    env = envelopes(r)
    ap = next(k for k in env if k.startswith("approve:"))
    # delegate: operation null, args = the edge dict, effect digest over ALL tx rows (marks included, seq order)
    m = commit_mark(r, "d1")
    rows = tx_log(r, m)
    assert [x["kind"] for x in rows if x["kind"] == "mark"] and rows == sorted(rows, key=lambda x: x["seq"])
    assert env["d1"]["decision"] == {"decision_id": "d1", "kind": "delegate", "subject": "planner-1", "on_behalf_of": None,
                                      "operation": None, "args_digest": sha(e1), "status": "OK", "reason": "ok",
                                      "effect_digest": sha(rows), "world_seq": m["seq"], "tick": m["tick"], "authority_path": []}
    # revoke: operation null, args = the edge_id STRING
    m = commit_mark(r, "rv")
    rows = tx_log(r, m)
    assert env["rv"]["decision"] == {"decision_id": "rv", "kind": "revoke", "subject": "planner-1", "on_behalf_of": None,
                                      "operation": None, "args_digest": sha("e1"), "status": "OK", "reason": "ok",
                                      "effect_digest": sha(rows), "world_seq": m["seq"], "tick": m["tick"], "authority_path": []}
    # call_tool/direct commit: args as passed, tick = the commit mark's tick
    m = commit_mark(r, "t1")
    rows = tx_log(r, m)
    assert any(x["kind"] == "mark" and x["ref"] == "commit" for x in rows) and len(rows) >= 2
    assert env["t1"]["decision"]["effect_digest"] == sha(rows) and env["t1"]["decision"]["args_digest"] == sha(TR)
    assert (env["t1"]["decision"]["world_seq"], env["t1"]["decision"]["tick"]) == (m["seq"], m["tick"])
    # refusal: no effects, world_seq = world_log head and tick = clock when deciding
    d2 = env["t2"]["decision"]
    assert (d2["effect_digest"], d2["world_seq"], d2["tick"], d2["operation"]) == (sha([]), refusal_head, refusal_tick, "transfer_inventory")
    # approve: args = the approved request's args dict itself (no wrapper); id unique within the stream
    da = env[ap]["decision"]
    assert da["args_digest"] == sha(BIG) and da["operation"] == "transfer_inventory" and da["kind"] == "approve"
    assert (da["effect_digest"], da["world_seq"], da["tick"]) == (sha([]), head, tick)
    assert len(env) == len({e["decision"]["decision_id"] for e in env.values()}) == 5


def test_e4_newest_tie_break_greatest_value_then_smallest_ref():
    from paladin import evid
    rows = [{"key": k, "version": 1, "props": {"f": v}} for k, v in (("B", 5), ("A", 5), ("C", 3))]
    ops = {"operations": [{"name": "o", "inputs": [], "business_rules": [{"newest": {"type": "T", "field": "f"}}],
                           "preconditions": []}]}
    out = evid.evidence_objects(ops, "o", {}, lambda t, k: next(x for x in rows if x["key"] == k), lambda t: rows)
    assert [e["ref"] for e in out] == ["T:A"]


def test_e3_delegate_under_v1_spec(tmp_path):
    v1 = load_auth_spec("manufacturing")
    assert v1["spec"] != "r3-authority-2"
    r = G2Rig(tmp_path, auth=None)
    r.dep.set_authority({**v1, "principals": v1["principals"] + [
        {"id": f"ag-{i}", "kind": "agent", "roles": [], "relations": [], "delegated_by": None} for i in (1, 2)],
        "grants": v1["grants"] + [r.auth["grants"][-1]]})
    assert r.dep.authority_state()["spec"] == v1["spec"]
    res = r.delegate("planner-1", edge("e1", "planner-1", "ag-1"), "v1-d")
    assert res.status == "OK", res
    st = r.dep.authority_state()
    assert st["spec"] == "r3-authority-2" and st["max_delegation_depth"] == 8 and st["revoked"] == []
    assert r.dep.authority_used("v1-d").status == "OK"
    assert r.transfer("ag-1", "planner-1", "v1-t").status == "OK"
    assert r.revoke("planner-1", "e1", "v1-rv").status == "OK"
    # authority_used / revoke / delegate while v1 in force on a fresh v1 deployment never raise
    (tmp_path / "x").mkdir()
    r2 = G2Rig(tmp_path / "x")
    r2.dep.set_authority(v1)
    assert r2.dep.authority_used("nope").status == "INVALID"
    assert r2.revoke("planner-1", "zz", "v1-rv2").status == "INVALID"
    assert r2.delegate("planner-1", {"bad": 1}, "v1-d2").status == "INVALID"


def test_e3_every_method_total_under_injected_failure(tmp_path):
    r = G2Rig(tmp_path)
    tok = r.token("planner-1")
    c = r.dep._c
    c.run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    c.mutate_authority = c.run
    c.ledger.get_meta = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    for res in (r.dep.direct(tok, "transfer_inventory", TR, request_id="i1"),
                r.dep.call_tool(tok, "transfer_inventory", TR, request_id="i2"),
                r.delegate("planner-1", edge("e1", "planner-1", "ag-1"), "i3"),
                r.revoke("planner-1", "e1", "i4"),
                r.dep.authority_used("i5"),
                r.dep.approve(None, "x", {}, "planner-1")):
        assert res.status in ("UNAVAILABLE", "DENIED", "INVALID", "UNKNOWN"), res
    assert r.dep.direct(tok, "transfer_inventory", TR, request_id="i1").body["reason"].startswith("internal_error")
    assert r.dep.replay("nope").status in ("UNRESOLVED", "TAMPERED")
