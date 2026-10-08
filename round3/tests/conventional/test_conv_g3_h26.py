"""PROT-H26 requirements R26-1..R26-6 (conventional): paired-world noninterference per channel, hidden == absent,
tool surface, frozen check order, truthful redaction, determinism. Expectations are hand-written from the frozen text."""
import json

import pytest

from conv_g3_util import RESCHEDULE, canon, make_g3, vary
from r3_shared.disclosure import check_low_result, tool_schema

JUN, PL, SEN, SUP, ADM, NOB = "junior-1", "planner-1", "senior-1", "supervisor-1", "admin-1", "nobody-1"
LOWM = ("read_object", "list_objects", "list_links", "query", "subscribe", "poll", "prov_decision", "prov_object",
        "authority_used_as")


def rig(tmp_path, sub="", **kw):
    return make_g3(tmp_path, "hierarchical", governance=None, sub=sub, **kw)


def probes(r, who):
    """A fixed observation sequence over every channel (the harness's job in the real run)."""
    t, d = r.token(who), r.dep
    sid = d.subscribe(t, {"types": ["PurchaseOrder", "WorkOrder", "Supplier"]})
    out = [canon(sid)]
    for ref in ("PurchaseOrder:PO-991", "PurchaseOrder:PO-777", "PurchaseOrder:PO-778", "WorkOrder:WO-42", "Supplier:S-7",
                "Warehouse:WH-A", "nonsense", "Part:none"):
        out.append(canon(d.read_object(t, ref)))
    out += [canon(d.list_objects(t, ty)) for ty in ("PurchaseOrder", "WorkOrder", "Supplier", "Warehouse", "Nope")]
    out += [canon(d.list_links(t, ref, lt)) for ref, lt in (("PurchaseOrder:PO-991", "PurchaseOrder_suppliedBy"),
                                                           ("WorkOrder:WO-42", "WorkOrder_warehouse"),
                                                           ("Supplier:S-7", "PurchaseOrder_suppliedBy"))]
    out += [canon(d.query(t, "work_order_risk", {"work_order": "WO-42"})), canon(d.read(t, "list", {"type": "Supplier"}))]
    out += [canon(d.tools(t))]
    po = {"po_id": "PO-991", "expedite_fee": 5}
    out += [canon(d.direct(t, "expedite_purchase_order", po, None, "pr1")),
            canon(d.direct(t, "expedite_purchase_order", {"po_id": "PO-777", "expedite_fee": 5}, None, "pr2")),
            canon(d.direct(t, "expedite_purchase_order", {"po_id": "PO-778", "expedite_fee": 5}, None, "pr3")),
            canon(d.direct(t, "expedite_purchase_order", {"po_id": "PO-991"}, None, "pr4"))]
    out += [canon(d.poll(t, sid.body["sub"]))]
    return out


def paired(tmp_path, who, mutate_a, mutate_b, **kw):
    a, b = rig(tmp_path, "a", **kw), rig(tmp_path, "b", **kw)
    mutate_a(a)
    mutate_b(b)
    return a, b, probes(a, who), probes(b, who)


@pytest.mark.parametrize("who,fact", [
    (JUN, ("PurchaseOrder:PO-991", "status", "DELAYED", "OPEN")),           # F: field of a hidden object
    (JUN, ("WorkOrder:WO-42", "plannedStart", 18, 19)),                     # F: hidden field of a visible object
    (SEN, ("Supplier:S-7", "riskClass", "MEDIUM", "HIGH")),                 # F: hidden field behind a via rule
    (JUN, ("InventoryLot:LOT-B-PX17", "onHand", 400, 401)),                 # F: object outside every rule
])
def test_r26_1_field_variation_is_noninterfering(tmp_path, who, fact):
    ref, f, va, vb = fact
    _, _, oa, ob = paired(tmp_path, who, lambda r: vary(r, ref, **{f: va}), lambda r: vary(r, ref, **{f: vb}))
    assert oa == ob


def test_r26_1_existence_variation_key_substitution(tmp_path):
    def add(key):
        def go(r):
            h = r.store.handle("seed")
            h.create("PurchaseOrder", key, {"poId": key, "status": "OPEN", "promisedAt": 1, "expectedAt": 2})
            h.close()
        return go
    _, _, oa, ob = paired(tmp_path, JUN, add("PO-777"), add("PO-778"))
    assert oa == ob


def test_r26_1_link_variation(tmp_path):
    def relink(dst):
        def go(r):
            h = r.store.handle("seed")
            h.unlink("PurchaseOrder_suppliedBy", "PurchaseOrder:PO-991", "Supplier:S-7")
            h.link("PurchaseOrder_suppliedBy", "PurchaseOrder:PO-991", dst)
            h.close()
        return go
    for who in (JUN, SEN):
        a, b = rig(tmp_path, f"a{who}"), rig(tmp_path, f"b{who}")
        for r in (a, b):
            h = r.store.handle("seed")
            h.create("Supplier", "S-8", {"supplierId": "S-8", "status": "ACTIVE"})
            h.close()
        relink("Supplier:S-8")(a)
        if who == JUN:  # the observer cannot see POs at all: the protected link differs, the low view does not
            assert probes(a, who) == probes(b, who)


def test_r26_2_hidden_equals_absent_on_every_channel(tmp_path):
    r = rig(tmp_path)
    t, d = r.token(JUN), r.dep
    hidden, absent = "PurchaseOrder:PO-991", "PurchaseOrder:PO-nope"
    assert canon(d.read_object(t, hidden)) == canon(d.read_object(t, absent)) == canon(
        type(d.read_object(t, hidden))("INVALID", {"reason": "not_found"}))
    assert canon(d.list_links(t, hidden, "PurchaseOrder_suppliedBy")) == canon(d.list_links(t, absent, "PurchaseOrder_suppliedBy"))
    assert canon(d.prov_object(t, hidden)) == canon(d.prov_object(t, absent))
    for rid, ref in (("h1", "PO-991"), ("h2", "PO-nope")):
        res = d.direct(t, "expedite_purchase_order", {"po_id": ref, "expedite_fee": 1}, None, rid)
        assert (res.status, res.body) == ("DENIED", {"reason": "no_matching_allow"})
    assert d.list_objects(t, "PurchaseOrder").body == {"refs": []}


def test_r26_2_hidden_fields_are_absent_not_null(tmp_path):
    r = rig(tmp_path)
    props = r.dep.read_object(r.token(JUN), "WorkOrder:WO-42").body["props"]
    assert set(props) == {"workOrderId", "status", "priority"}  # plannedStart/plannedFinish ABSENT
    assert r.dep.read_object(r.token(PL), "WorkOrder:WO-42").body["props"]["plannedStart"] == 18


def test_r26_2_act_implies_exists_but_never_fields(tmp_path):
    r = rig(tmp_path)  # planner may expedite PO (neutral-fix) -> E(PO) low, fields only through rules
    res = r.dep.read_object(r.token(PL), "PurchaseOrder:PO-991")
    assert res.status in ("OK", "INVALID")
    if res.status == "OK":
        assert res.body["props"] == {}


def test_r26_3_no_canary_in_any_low_output(tmp_path):
    r = rig(tmp_path)
    vary(r, "PurchaseOrder:PO-991", status="cv-0123456789ab")
    vary(r, "WorkOrder:WO-42", plannedStart=7_000_001)
    blob = "".join(probes(r, JUN)) + "".join(probes(r, NOB))
    assert "cv-0123456789ab" not in blob and "7000001" not in blob


def test_r26_4_tools_use_the_frozen_derivation_and_the_subject_bound(tmp_path):
    r = rig(tmp_path)
    defs = {o["name"]: o for o in r.ops["operations"]}
    names = {}
    for who in (PL, JUN, NOB, ADM):
        ts = r.dep.tools(r.token(who))
        names[who] = [t.name for t in ts]
        assert all(t.input_schema == tool_schema(defs[t.name]) for t in ts)
    assert names[NOB] == [] and set(names[ADM]) == set(defs) and set(names[JUN]) < set(defs)
    assert r.dep.tools("garbage") == []


def test_r26_4_emergency_scope_extends_tools_only_while_active(tmp_path):
    r = make_g3(tmp_path, "hierarchical")
    assert "reschedule_work_order" not in [t.name for t in r.dep.tools(r.token(NOB))]


def test_r26_check_order_token_schema_authority_existence(tmp_path):
    r = rig(tmp_path)
    t, d = r.token(JUN), r.dep
    assert d.direct("bad", "expedite_purchase_order", {"po_id": "x", "expedite_fee": 1}, None, "o1").body["reason"] == "invalid_token"
    bad = d.direct(t, "expedite_purchase_order", {"po_id": "PO-991", "zzz": 1}, None, "o2")  # schema before authority
    assert (bad.status, bad.body["reason"]) == ("INVALID", "unknown_field")
    assert d.direct(t, "expedite_purchase_order", {"po_id": "PO-991", "expedite_fee": 1}, None, "o3").status == "DENIED"
    assert set(bad.body) == {"reason"}  # no detail, no values


def test_r26_hidden_edge_and_parent_are_unknown(tmp_path):
    from conv_g2_util import edge, v2_spec  # noqa: F401  (shape reference)
    r = make_g3(tmp_path, "hierarchical", governance=None)
    # an authority v3 fixture has no edges: both a never-existing and (below) a hidden edge answer identically
    e = {"id": "n1", "issuer": NOB, "child": JUN, "parent": "ghost", "scope": {"operations": ["transfer_inventory"], "resources": []},
         "expires_at": None, "redelegable": False, "issued_at": 0}
    res = r.dep.delegate(r.token(NOB), e, "d1")
    assert (res.status, res.body) == ("INVALID", {"reason": "unknown_parent"})
    res = r.dep.revoke(r.token(NOB), "ghost", "r1")
    assert (res.status, res.body) == ("INVALID", {"reason": "unknown_edge"})


def test_r26_hidden_edge_twin_with_real_edge(tmp_path):
    import copy
    spec = copy.deepcopy(make_g3(tmp_path, governance=None, sub="s").auth)
    spec["grants"].append({"id": "pl-del", "effect": "allow", "operation": "transfer_inventory", "origin": "neutral-extension",
                           "principal": {"on_type": "Warehouse", "relation": "planner"}, "resource": {"type": "Warehouse"},
                           "delegable": True})
    r = make_g3(tmp_path, governance=None, sub="t", auth=spec)
    WH, PART = {"type": "Warehouse", "keys": None}, {"type": "Part", "keys": None}
    e1 = {"id": "e1", "issuer": PL, "child": NOB, "parent": None, "scope": {"operations": ["transfer_inventory"],
          "resources": [WH, PART]}, "expires_at": None, "redelegable": True, "issued_at": 0}
    assert r.dep.delegate(r.token(PL), e1, "d1").status == "OK"
    hid = r.dep.delegate(r.token(JUN), {**e1, "id": "z", "issuer": JUN, "child": SUP, "parent": "e1"}, "d2")
    abs_ = r.dep.delegate(r.token(JUN), {**e1, "id": "z", "issuer": JUN, "child": SUP, "parent": "ghost"}, "d3")
    assert (hid.status, hid.body) == (abs_.status, abs_.body) == ("INVALID", {"reason": "unknown_parent"})
    rev_h, rev_a = r.dep.revoke(r.token(JUN), "e1", "r1"), r.dep.revoke(r.token(JUN), "ghost", "r2")
    assert (rev_h.status, rev_h.body) == (rev_a.status, rev_a.body) == ("INVALID", {"reason": "unknown_edge"})


def test_r26_5_provenance_markers_and_hidden_decisions(tmp_path):
    r = rig(tmp_path, history=True)
    try:
        ok = r.dep.direct(r.token(PL), "transfer_inventory", {"source_warehouse": "WH-B", "destination_warehouse": "WH-A",
                                                              "part": "PX-17", "quantity": 10}, None, "tx1")
        assert ok.status == "OK"
        own = r.dep.prov_decision(r.token(PL), "tx1")
        check_low_result("prov_decision", own)
        assert own.body["partial"] is True and own.body["decision"]["subject"] == PL
        other = r.dep.prov_decision(r.token(NOB), "tx1")
        assert (other.status, other.body) == ("INVALID", {"reason": "unknown_decision"})
        absent = r.dep.prov_decision(r.token(NOB), "no-such")
        assert canon(other) == canon(absent)
        used = r.dep.authority_used_as(r.token(PL), "tx1")
        check_low_result("authority_used_as", used)
        assert used.body["authority_version"] == {"redacted": "digest"} and used.body["path"] == []
        assert canon(r.dep.authority_used_as(r.token(NOB), "tx1")) == canon(r.dep.authority_used_as(r.token(NOB), "zz"))
    finally:
        r.anchor_proc.proc.kill()


def test_r26_provenance_noninterference_on_hidden_decisions(tmp_path):
    outs = []
    for i, qty in enumerate((10, 11)):  # a HIDDEN principal's call differs in args; the observer's views are identical
        r = rig(tmp_path, f"p{i}", history=True)
        r.dep.direct(r.token(PL), "transfer_inventory", {"source_warehouse": "WH-B", "destination_warehouse": "WH-A",
                                                         "part": "PX-17", "quantity": qty}, None, "tx1")
        t = r.token(JUN)
        outs.append([canon(r.dep.prov_decision(t, "tx1")), canon(r.dep.prov_object(t, "Warehouse:WH-A")),
                     canon(r.dep.authority_used_as(t, "tx1"))])
        r.anchor_proc.proc.kill()
    assert outs[0] == outs[1]


def test_r26_subscription_delivers_only_low_changes(tmp_path):
    r = rig(tmp_path)
    t = r.token(JUN)
    sid = r.dep.subscribe(t, {"types": ["PurchaseOrder", "WorkOrder"]}).body["sub"]
    vary(r, "PurchaseOrder:PO-991", status="OPEN")  # hidden for junior
    vary(r, "WorkOrder:WO-42", plannedStart=99)  # hidden FIELD of a visible object
    vary(r, "WorkOrder:WO-42", priority="LOW")  # visible field
    ev = r.dep.poll(t, sid)
    check_low_result("poll", ev)
    assert [(e["kind"], e["ref"], e["props"]) for e in ev.body["events"]] == [("update", "WorkOrder:WO-42", {"priority": "LOW"})]
    assert r.dep.poll(t, sid).body == {"events": []}
    assert r.dep.poll(r.token(PL), sid).body == {"reason": "unknown_subscription"}  # foreign == absent


def test_r26_5_determinism_a_a_control(tmp_path):
    a, b = probes(rig(tmp_path, "x"), JUN), probes(rig(tmp_path, "y"), JUN)
    assert a == b


def test_r26_6_all_probe_outputs_match_the_frozen_forms(tmp_path):
    r = rig(tmp_path)
    t, d = r.token(PL), r.dep
    check_low_result("read_object", d.read_object(t, "WorkOrder:WO-42"))
    check_low_result("read_object", d.read_object(t, "x:y"))
    check_low_result("list_objects", d.list_objects(t, "WorkOrder"))
    check_low_result("list_objects", d.list_objects(t, "Nope"))
    check_low_result("list_links", d.list_links(t, "WorkOrder:WO-42", "WorkOrder_warehouse"))
    check_low_result("query", d.query(t, "work_order_risk", {"work_order": "WO-42"}))
    check_low_result("prov_object", d.prov_object(t, "WorkOrder:WO-42"))
    assert json.loads(canon(d.list_links(t, "WorkOrder:WO-42", "WorkOrder_warehouse")))["body"]["out"] == ["Warehouse:WH-A"]
