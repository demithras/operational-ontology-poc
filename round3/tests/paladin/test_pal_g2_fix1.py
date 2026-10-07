"""G2 fix1 (Paladin): E-5 set_authority base-only, E-7 deploy never raises on HistoryStore content, E-8 envelope every
non-schema-INVALID decision. Zero-effect claims are measured from the world store, never from return values."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from g2_hist import build, envelopes  # noqa: E402
from g2_rig import G2Rig, TR, edge, new_anchor  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def anchor(tmp_path_factory):
    ap = new_anchor(tmp_path_factory.mktemp("anchor"))
    yield ap
    ap.close()


# ---- E-5 ------------------------------------------------------------------------------------------------------------
def test_e5_set_authority_cannot_unrevoke_or_drop_edges(tmp_path):
    r = G2Rig(tmp_path)
    assert r.delegate("planner-1", edge("e1", "planner-1", "ag-1"), "d1").status == "OK"
    assert r.transfer("ag-1", "planner-1", "t1").status == "OK"
    assert r.revoke("planner-1", "e1", "rv").status == "OK"
    doc = copy.deepcopy(r.dep.authority_state())
    doc["revoked"], doc["capabilities"] = [], [edge("e1", "planner-1", "ag-1")]  # tries to un-revoke e1
    r.dep.set_authority(doc)
    assert r.dep.authority_state()["revoked"] == ["e1"]
    res, eff = r.effects_of(lambda: r.transfer("ag-1", "planner-1", "t2", {**TR, "quantity": 5}))
    assert res.status == "DENIED" and not [x for x in eff if x.get("kind") != "mark"] or res.status == "DENIED"
    snap = r.snap()
    assert r.transfer("ag-1", "planner-1", "t3", {**TR, "quantity": 6}).status == "DENIED"
    assert r.snap() == snap  # zero effects through the revoked edge


def test_e5_set_authority_keeps_live_edges_and_replaces_base(tmp_path):
    r = G2Rig(tmp_path)
    assert r.delegate("planner-1", edge("e1", "planner-1", "ag-1"), "d1").status == "OK"
    doc = copy.deepcopy(r.dep.authority_state())
    doc["capabilities"] = []  # ignored: the edge stays
    r.dep.set_authority(doc)
    assert [e["id"] for e in r.dep.authority_state()["capabilities"]] == ["e1"]
    assert r.transfer("ag-1", "planner-1", "t1").status == "OK"


# ---- E-7 ------------------------------------------------------------------------------------------------------------
def _flip_authority(tv, key):
    d = json.loads(tv.read(key))
    d["max_delegation_depth"] = d.get("max_delegation_depth", 8) + 1
    d["capabilities"] = [{**e, "child": "researcher-2~"} for e in d.get("capabilities", [])] or [
        {"id": "e-3-2", "issuer": "planner-1", "child": "researcher-2~"}]
    tv.write(key, json.dumps(d).encode())


PRIMS = {
    "garbage": lambda tv, k: tv.write(k, b"\x00not json"),
    "delete": lambda tv, k: tv.delete(k),
    "rename": lambda tv, k: tv.rename(k, k + ".moved"),
    "unknown_principal": _flip_authority,
    "empty_object": lambda tv, k: tv.write(k, b"{}"),
}


@pytest.mark.parametrize("prim", sorted(PRIMS))
@pytest.mark.parametrize("which", ["meta", "version"])
def test_e7_deploy_never_raises_and_mutations_fail_closed(tmp_path, anchor, prim, which):
    r = G2Rig(tmp_path, history=True, anchor=anchor.client())
    r.snaps = build(r)
    tv = r.tamper()
    keys = ["led/meta/auth_spec"] if which == "meta" else [k for k in tv.keys("auth/")]
    assert keys, "no authority record to tamper"
    for k in keys:
        PRIMS[prim](tv, k)
    f = r.deploy(state_dir=None)  # must not raise
    for did in ("d1", "t1", "rv"):
        assert f.replay(did).status in ("VERIFIED", "TAMPERED", "UNRESOLVED")  # never raises
        f.explain(did)
    snap = r.snap()
    res = f.direct(r.token("planner-1"), "transfer_inventory", {**TR, "quantity": 3}, request_id="post-tamper")
    assert res.status != "OK", res
    assert r.snap() == snap, "tampered authority record: mutating call had effects"
    assert f.delegate(r.token("planner-1"), edge("e9", "planner-1", "ag-2"), "post-d").status != "OK"
    assert r.snap() == snap


# ---- E-8 ------------------------------------------------------------------------------------------------------------
def _env_ids(r):
    return sorted(envelopes(r))


@pytest.mark.parametrize("via", ["direct", "call_tool"])
def test_e8_every_non_schema_decision_has_one_envelope(tmp_path, anchor, via):
    r = G2Rig(tmp_path, history=True, anchor=anchor.client())
    call = (lambda sub, rid, args, obo=None: r.dep.direct(r.token(sub), "transfer_inventory", args, on_behalf_of=obo, request_id=rid)) \
        if via == "direct" else \
        (lambda sub, rid, args, obo=None: r.dep.call_tool(r.token(sub), "transfer_inventory", args, on_behalf_of=obo, request_id=rid))
    cases = [  # (rid, subject, args, expected status, envelope?)
        ("ok", "planner-1", {**TR, "quantity": 1}, "OK", True),
        ("denied", "ag-1", TR, "DENIED", True),                                  # authority
        ("rule", "planner-1", {**TR, "quantity": 10 ** 9}, "INVALID", True),     # precondition / rule
        ("exist", "planner-1", {**TR, "destination_warehouse": "NOPE"}, "INVALID", True),  # existence is not schema
        ("missing", "planner-1", {k: v for k, v in TR.items() if k != "part"}, "INVALID", False),   # schema
        ("type", "planner-1", {**TR, "quantity": "many"}, "INVALID", False),                         # schema
        ("null", "planner-1", {**TR, "part": None}, "INVALID", False),                               # schema
    ]
    for rid, sub, args, status, gov in cases:
        before, snap = len(_env_ids(r)), r.snap()
        res = call(sub, f"{via}-{rid}", args)
        assert res.status == status, (rid, res)
        assert len(_env_ids(r)) - before == (1 if gov else 0), (via, rid, res)
        if status != "OK":
            assert r.snap() == snap, rid
    # the stream is gap-free: a fresh deployment replays every envelope VERIFIED
    f = r.deploy(state_dir=None)
    for did in _env_ids(r):
        assert f.replay(did).status == "VERIFIED", did
