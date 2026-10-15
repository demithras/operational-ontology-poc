"""G2 fix round 1 (conventional): E-5 base-only set_authority, no-op revoke writes no world transaction, E-6 required-ref
existence, E-7 deploy never raises on HistoryStore content, E-8 every non-schema-INVALID decision has an envelope."""
import copy
import json

import pytest

from conv_g2_util import PART, TRANSFER, WH, edge, make_g2, sha, tamper
from conv_helpers import VALID
from r3_shared.authspec import load_auth_spec
from r3_shared.world import diff

PLANNER, NOBODY, JUNIOR = "planner-1", "nobody-1", "junior-1"


@pytest.fixture
def rig(tmp_path):
    r = make_g2(tmp_path)
    yield r
    r.close()


@pytest.fixture
def hrig(tmp_path):
    r = make_g2(tmp_path, with_history=True)
    yield r
    r.close()


def use(r, rid, qty=10):
    return r.dep.direct(r.token(NOBODY), "transfer_inventory", {**TRANSFER, "quantity": qty}, PLANNER, rid)


# ---- E-5 ------------------------------------------------------------------------------------------------------------
def test_e5_set_authority_cannot_unrevoke_or_drop_edges(rig):
    assert rig.dep.delegate(rig.token(PLANNER), edge("e1", PLANNER, NOBODY), "d0").status == "OK"
    assert rig.dep.delegate(rig.token(PLANNER), edge("e2", PLANNER, JUNIOR), "d1").status == "OK"
    assert rig.dep.revoke(rig.token(PLANNER), "e1", "rv").status == "OK"
    doc = copy.deepcopy(rig.auth)
    doc["capabilities"], doc["revoked"] = [], []  # a document that lists e1 unrevoked and no edges at all
    rig.dep.set_authority(doc)
    st = rig.dep.authority_state()
    assert [e["id"] for e in st["capabilities"]] == ["e1", "e2"] and st["revoked"] == ["e1"]
    before = rig.snap()
    assert use(rig, "u").body["reason"] == "no_valid_path" and diff(before, rig.snap()) == []


def test_e5_set_authority_ignores_capabilities_in_the_document(rig):
    doc = copy.deepcopy(rig.auth)
    doc["capabilities"] = [edge("sneak", PLANNER, NOBODY)]
    rig.dep.set_authority(doc)
    assert rig.dep.authority_state()["capabilities"] == []
    before = rig.snap()
    assert use(rig, "u").status == "DENIED" and diff(before, rig.snap()) == []


def test_e5_base_layer_is_replaced(rig):
    assert rig.dep.delegate(rig.token(PLANNER), edge("e1", PLANNER, NOBODY), "d0").status == "OK"
    doc = copy.deepcopy(rig.auth)
    doc["grants"] = [g for g in doc["grants"] if g["operation"] != "transfer_inventory"]
    rig.dep.set_authority(doc)  # planner no longer holds the grant: the edge (edges persist) cannot be exercised
    before = rig.snap()
    assert use(rig, "u").status == "DENIED" and diff(before, rig.snap()) == []
    assert [e["id"] for e in rig.dep.authority_state()["capabilities"]] == ["e1"]


# ---- no-op revoke ---------------------------------------------------------------------------------------------------
def test_noop_revoke_writes_no_world_transaction(rig):
    assert rig.dep.delegate(rig.token(PLANNER), edge("e1", PLANNER, NOBODY), "d0").status == "OK"
    assert rig.dep.revoke(rig.token(PLANNER), "e1", "rv1").status == "OK"
    log, snap = rig.log(), rig.snap()
    again = rig.dep.revoke(rig.token(PLANNER), "e1", "rv2")
    assert again.status == "OK" and again.body == {"already": True}
    assert rig.log() == log and diff(snap, rig.snap()) == []
    assert rig.dep.revoke(rig.token(PLANNER), "e1", "rv2").status == "OK"  # a retry of the no-op is still fine
    assert rig.log() == log
    assert rig.dep.authority_used("rv2").status == "INVALID"  # no commit mark was written for it


# ---- E-6 ------------------------------------------------------------------------------------------------------------
def test_e6_nonexistent_destination_warehouse_is_invalid_zero_effects(rig):
    before = rig.snap()
    r = rig.dep.direct(rig.token("admin-1"), "transfer_inventory", {**TRANSFER, "destination_warehouse": "NOPE"}, None, "n")
    assert r.status == "INVALID" and r.body["reason"] == "target_not_found"
    assert diff(before, rig.snap()) == []


@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_e6_sweep_every_resource_input_of_every_operation(tmp_path, domain):
    r = make_g2(tmp_path, domain=domain, spec=load_auth_spec(domain))
    try:
        n = invalid = 0
        for op in r.ops["operations"]:
            for inp in op["inputs"]:
                if inp["type"] != "resource":
                    continue
                n += 1
                before = r.snap()
                res = r.dep.direct(r.token("admin-1"), op["name"], {**VALID[op["name"]], inp["name"]: "NOPE-NOT-THERE"},
                                   None, f"s-{op['name']}-{inp['name']}")
                assert res.status in ("INVALID", "DENIED"), (op["name"], inp["name"], res)
                assert diff(before, r.snap()) == [], (op["name"], inp["name"])
                invalid += res.status == "INVALID"
        assert n >= 3 and invalid >= 1
    finally:
        r.close()


# ---- E-7 ------------------------------------------------------------------------------------------------------------
def _auth_key(r):
    return f"art/{r.dep.authority_version()}"


PRIMITIVES = ["garbage", "other_valid_json", "delete", "rename"]


def _apply(r, how, key=None):
    t, k = tamper(r), key or _auth_key(r)
    raw = t.read(k)
    if how == "garbage":
        t.write(k, b"\x00not json")
    elif how == "other_valid_json":
        d = json.loads(raw)
        d["grants"] = []
        t.write(k, json.dumps(d, sort_keys=True).encode())
    elif how == "delete":
        t.delete(k)
    else:
        t.rename(k, "art/" + "0" * 64)
    assert t.log()


@pytest.mark.parametrize("with_edge", [False, True])
@pytest.mark.parametrize("how", PRIMITIVES)
def test_e7_deploy_never_raises_and_dependent_calls_have_zero_effects(hrig, how, with_edge):
    r = hrig
    if with_edge:
        assert r.dep.delegate(r.token(PLANNER), edge("e1", PLANNER, NOBODY), "d0").status == "OK"
    ok = r.dep.direct(r.token(PLANNER), "transfer_inventory", {**TRANSFER, "quantity": 1}, None, "x1")
    assert ok.status == "OK"
    _apply(r, how)
    fresh = r.redeploy()  # must not raise
    before, log = r.snap(), r.log()
    for res in (fresh.direct(r.token(PLANNER), "transfer_inventory", {**TRANSFER, "quantity": 2}, None, "x2"),
                fresh.call_tool(r.token(PLANNER), "transfer_inventory", {**TRANSFER, "quantity": 2}, None, "x3"),
                fresh.delegate(r.token(PLANNER), edge("e9", PLANNER, NOBODY), "d9"),
                fresh.revoke(r.token(PLANNER), "e1", "rv9"),
                fresh.direct(r.token(PLANNER), "transfer_inventory", {**TRANSFER, "quantity": 1}, None, "x1")):
        assert res.status != "OK", res
    assert diff(before, r.snap()) == [] and r.log() == log
    rep = fresh.replay("x1")
    assert rep.status in ("TAMPERED", "UNRESOLVED"), rep
    assert fresh.explain("x1").status == rep.status


def test_e7_restart_over_damaged_lineage_stays_up_and_refuses(hrig):
    r = hrig
    assert r.dep.delegate(r.token(PLANNER), edge("e1", PLANNER, NOBODY), "d0").status == "OK"
    key = _auth_key(r)
    r.dep.crash()
    _apply(r, "garbage", key)
    r.dep.restart()  # must not raise
    before = r.snap()
    assert use(r, "u").status != "OK" and diff(before, r.snap()) == []


def test_e7_untampered_redeploy_still_continues_the_lineage(hrig):
    r = hrig
    assert r.dep.delegate(r.token(PLANNER), edge("e1", PLANNER, NOBODY), "d0").status == "OK"
    fresh = r.redeploy()
    assert fresh.authority_state()["capabilities"][0]["id"] == "e1"
    assert fresh.direct(r.token(NOBODY), "transfer_inventory", TRANSFER, PLANNER, "u").status == "OK"


# ---- E-8 ------------------------------------------------------------------------------------------------------------
def _envs(r):
    return len(r.history.keys("env/"))


KINDS = ["call_tool", "direct"]


def _send(r, kind, who, op, args, rid, obo=None):
    return getattr(r.dep, kind)(r.token(who), op, args, obo, rid)


@pytest.mark.parametrize("kind", KINDS)
def test_e8_envelope_for_ok_denied_invalid_rule(hrig, kind):
    r = hrig
    cases = [
        ("OK", PLANNER, "transfer_inventory", {**TRANSFER, "quantity": 1}),
        ("DENIED", JUNIOR, "transfer_inventory", {**TRANSFER, "quantity": 1}),  # authority (tool hidden / no grant)
        ("DENIED", NOBODY, "expedite_purchase_order", {"po_id": "PO-991", "expedite_fee": 1}),  # no grant at all
        ("DENIED", PLANNER, "expedite_purchase_order", {"po_id": "PO-NOPE", "expedite_fee": 1}),  # business rule
        ("INVALID", PLANNER, "transfer_inventory", {**TRANSFER, "quantity": 0}),  # precondition only (G3-E17)
        ("INVALID", "admin-1", "transfer_inventory", {**TRANSFER, "destination_warehouse": "NOPE"}),  # E-6 target
    ]
    for i, (want, who, op, args) in enumerate(cases):
        n = _envs(r)
        res = _send(r, kind, who, op, args, f"{kind}-{i}")
        assert res.status == want, (i, res)
        assert _envs(r) == n + 1, (kind, i, res)
        env = json.loads(r.history.get(f"env/{n + 1:010d}"))
        assert env["decision"]["status"] == res.status and env["decision"]["kind"] == kind
        assert r.dep.replay(f"{kind}-{i}").status == "VERIFIED"


@pytest.mark.parametrize("kind", KINDS)
def test_e8_schema_invalid_has_no_envelope_whatever_the_subject(hrig, kind):
    r = hrig
    bad = [{**TRANSFER, "quantity": "ten"}, {**TRANSFER, "bogus": 1}, {"part": "PX-17"}, "not-an-object"]
    for who in (PLANNER, JUNIOR, NOBODY):
        for i, args in enumerate(bad):
            n = _envs(r)
            res = _send(r, kind, who, "transfer_inventory", args, f"b-{kind}-{who}-{i}")
            assert res.status in ("INVALID", "DENIED"), res
            assert _envs(r) == n, (kind, who, args, res)


@pytest.mark.parametrize("kind", KINDS)
def test_e8_unknown_tool_name_is_not_a_decision(hrig, kind):
    n = _envs(hrig)
    assert _send(hrig, kind, PLANNER, "no_such_operation", {}, "u1").status in ("INVALID", "DENIED")
    assert _envs(hrig) == n


def test_e8_retry_of_a_committed_call_tool_adds_no_envelope(hrig):
    r = hrig
    assert _send(r, "call_tool", PLANNER, "transfer_inventory", {**TRANSFER, "quantity": 1}, "r1").status == "OK"
    n = _envs(r)
    again = _send(r, "call_tool", PLANNER, "transfer_inventory", {**TRANSFER, "quantity": 1}, "r1")
    assert again.status == "OK" and _envs(r) == n


def test_e8_denied_call_tool_does_not_shift_later_decisions(hrig):
    r = hrig
    _send(r, "call_tool", JUNIOR, "transfer_inventory", {**TRANSFER, "quantity": 1}, "a")
    _send(r, "call_tool", PLANNER, "transfer_inventory", {**TRANSFER, "quantity": 1}, "b")
    seqs = [json.loads(r.history.get(k))["decision"]["decision_id"] for k in sorted(r.history.keys("env/"))]
    assert seqs == ["a", "b"]
    assert r.dep.replay("a").status == "VERIFIED" and r.dep.replay("b").status == "VERIFIED"
    assert sha(b"x") and WH and PART  # keep shared imports referenced
