"""Gate 2 on the second domain (project: canonical writes through the service transaction) + approval-chain exclusion."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g2_hist import BIG, build, sha  # noqa: E402
from g2_rig import G2Rig, edge, new_anchor, v2_mfg  # noqa: E402
from r3_shared.authspec import load_auth_spec  # noqa: E402


def v2_project() -> dict:
    a = copy.deepcopy(load_auth_spec("project"))
    a["spec"], a["max_delegation_depth"], a["capabilities"], a["revoked"] = "r3-authority-2", 8, [], []
    g = copy.deepcopy(next(x for x in a["grants"] if x["id"] == "researcher-create-hypothesis"))
    g.update(id="g24-researcher-create", delegable=True, origin="neutral-extension")
    a["grants"].append(g)
    return a


def mk(tmp_path, **kw):
    return G2Rig(tmp_path, domain="project", auth=v2_project(), **kw)


def create(r, sub, obo, rid, claim="claim one"):
    return r.dep.direct(r.token(sub), "create_hypothesis", {"claim": claim}, on_behalf_of=obo, request_id=rid)


E = dict(ops=["create_hypothesis"], resources=[])


def test_project_edge_effect_revocation_and_marks(tmp_path):
    r = mk(tmp_path)
    assert r.delegate("researcher-1", edge("e", "researcher-1", "viewer-1", **E)).status == "OK"
    res, eff = r.effects_of(lambda: create(r, "viewer-1", "researcher-1", "c1"))
    assert res.status == "OK" and [e["kind"] for e in eff] == ["create"]
    tx = {m["tx"] for m in r.log() if m["kind"] == "mark" and m["ref"] == "commit" and m["data"]["request_id"] == "c1"}
    assert {x["tx"] for x in r.log() if x["kind"] == "create" and x["writer"] == "paladin-service"} >= tx  # effect + mark: ONE tx
    assert r.revoke("researcher-1", "e").status == "OK"
    res, eff = r.effects_of(lambda: create(r, "viewer-1", "researcher-1", "c2", "claim two"))
    assert res.status == "DENIED" and eff == []
    assert create(r, "viewer-1", None, "c3").status == "DENIED"  # no on_behalf_of: viewer's own (empty) authority, no fallback to the edge


def test_project_history_replays_and_detects_tamper(tmp_path):
    ap = new_anchor(tmp_path)
    try:
        r = mk(tmp_path, history=True, anchor=ap.client())
        assert r.delegate("researcher-1", edge("e", "researcher-1", "viewer-1", **E), "d").status == "OK"
        assert create(r, "viewer-1", "researcher-1", "c1").status == "OK"
        assert create(r, "viewer-1", None, "c2", "x").status == "DENIED"
        f = r.deploy(state_dir=None)
        assert [f.replay(d).status for d in ("d", "c1", "c2")] == ["VERIFIED"] * 3
        tv = r.tamper()
        env = [k for k in tv.keys("env/")][1]
        tv.write(env, tv.read(env) + b" ")
        assert r.deploy(state_dir=None).replay("c1").status == "TAMPERED"
    finally:
        ap.close()


def test_approval_excludes_every_issuer_on_the_edge_path(tmp_path):
    r = G2Rig(tmp_path)
    assert r.delegate("admin-1", edge("a", "admin-1", "ag-1")).status == "OK"
    assert r.delegate("ag-1", edge("b", "ag-1", "ag-2", "a")).status == "OK"
    c = r.dep._c
    assert c.excluded_approvers("ag-2", "admin-1") == {"admin-1", "ag-1", "ag-2"} and c.excluded_approvers("ag-2", None) == {"ag-2"}
    t = r.token("ag-2")
    assert r.dep.direct(t, "transfer_inventory", BIG, on_behalf_of="admin-1", request_id="big").body["reason"] == "approval_required"
    for approver in ("admin-1", "ag-1", "ag-2"):  # Q and every issuer: refused even where the principal holds the capability
        assert r.dep.approve(r.token(approver), "transfer_inventory", BIG, "ag-2", "admin-1").status == "DENIED", approver
    n = len(r.snap()["effects"])
    assert r.dep.direct(t, "transfer_inventory", BIG, on_behalf_of="admin-1", request_id="big2").status == "DENIED"
    assert r.dep.approve(r.token("senior-1"), "transfer_inventory", BIG, "ag-2", "admin-1").status == "OK"
    assert r.dep.direct(t, "transfer_inventory", BIG, on_behalf_of="admin-1", request_id="big3").status == "OK"
    assert len(r.snap()["effects"]) == n + 1
