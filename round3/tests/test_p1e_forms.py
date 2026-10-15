import json

import pytest

from r3_shared import constitutional as C
from r3_shared import disclosure as D
from r3_shared.opsspec import load_ops_spec
from r3_shared.variant import CallResult, G3_METHODS, G3_MISSING, g3_call
from r3_shared import mutants


@pytest.mark.parametrize("dom", ["manufacturing", "project"])
def test_tool_schema_every_op_deterministic(dom):
    ops = load_ops_spec(dom)
    for op in ops["operations"]:
        s = D.tool_schema(op)
        assert json.dumps(s, sort_keys=True) == json.dumps(D.tool_schema(json.loads(json.dumps(op))), sort_keys=True)
        assert s["type"] == "object" and s["additionalProperties"] is False
        assert s["required"] == sorted(i["name"] for i in op["inputs"] if i["required"])
        assert set(s["properties"]) == {i["name"] for i in op["inputs"]}
        for i in op["inputs"]:
            p = s["properties"][i["name"]]
            assert set(p) <= {"type", "resource_type"}
            assert ("resource_type" in p) == (i["type"] == "resource")


def test_tool_schema_json_typed_input_has_no_type_and_integer_is_integer():
    op = {"inputs": [{"name": "v", "type": "json", "required": True}, {"name": "n", "type": "integer", "required": False},
                     {"name": "r", "type": "resource", "resource_type": "Part", "required": True}]}
    s = D.tool_schema(op)
    assert s["properties"] == {"v": {}, "n": {"type": "integer"}, "r": {"type": "string", "resource_type": "Part"}}
    assert s["required"] == ["r", "v"]


def test_emergency_declare_pseudo_op_schema():
    s = D.tool_schema(C.EMERGENCY_DECLARE_OP)
    assert s["required"] == ["emergency", "expires_at", "grantees", "scope"]
    assert s["properties"]["expires_at"] == {"type": "integer"}


GOOD = {
    "propose": {"kind": "propose", "case": "c1", "operation": "o", "args": {}, "on_behalf_of": None},
    "judge": {"kind": "judge", "case": "c1", "stage": "decision", "value": "concur", "merit": "m"},
    "appeal": {"kind": "appeal", "case": "c1"},
    "execute": {"kind": "execute", "case": "c1"},
    "act": {"kind": "act", "emergency": "e1", "operation": "o", "args": {}},
    "end": {"kind": "end", "emergency": "e1"},
}


@pytest.mark.parametrize("kind", sorted(GOOD))
def test_action_schema_accepts_good(kind):
    assert C.check_action(GOOD[kind]) is None


def test_action_schema_reject_table():
    bad = [None, [], {}, {"kind": "nope"}]
    for k, a in GOOD.items():
        bad.append({**a, "extra": 1})
        for f in a:
            if f != "kind":
                bad.append({x: y for x, y in a.items() if x != f})
                bad.append({**a, f: 7})
    bad += [{**GOOD["judge"], "value": "uphold"}, {**GOOD["judge"], "stage": "review", "value": "concur"},
            {**GOOD["judge"], "stage": "appeal"}, {**GOOD["propose"], "on_behalf_of": 3}, {**GOOD["propose"], "args": []}]
    assert all(C.check_action(b) == "schema" for b in bad)
    assert C.check_action({**GOOD["judge"], "stage": "review", "value": "overturn"}) is None
    assert C.check_action({**GOOD["propose"], "on_behalf_of": "p-1"}) is None


def test_ok_and_refusal_bodies():
    assert C.ok_body("propose", case="c", bodies=["b", "a"]) == {"case": "c", "bodies": ["a", "b"]}
    assert C.ok_body("judge", case="c", stage="review") == {"case": "c", "stage": "review"}
    assert C.ok_body("appeal", case="c") == {"case": "c"} and C.ok_body("end", emergency="e") == {"emergency": "e"}
    with pytest.raises(ValueError):
        C.ok_body("execute", case="c")
    assert C.refusal_body("oracle_needed") == {"reason": "oracle_needed"}
    with pytest.raises(ValueError):
        C.refusal_body("forbidden")


def test_governance_marks_exact_keys_and_digests():
    p = C.governance_mark("propose", case="c", requester="r", on_behalf_of=None, operation="o", args={"a": 1}, bodies=["z", "a"])
    assert p["bodies"] == ["a", "z"] and p["args_digest"] == C.args_digest({"a": 1}) and len(p["args_digest"]) == 64
    j = C.governance_mark("judge", case="c", stage="decision", judge="p", value="concur", merit="because")
    assert j["merit_digest"] == C.merit_digest("because") != C.merit_digest("other")
    assert C.governance_mark("execute", case="c", rule="lapse", basis=[])["outcome"] == "ALLOW"
    assert C.governance_mark("set_governance", doc={"a": 1})["version"] == C.digest({"a": 1})
    for op in ("appeal", "end", "act"):
        kw = {"appeal": dict(case="c", by="p"), "end": dict(emergency="e"),
              "act": dict(emergency="e", operation="o", args={})}[op]
        assert set(C.governance_mark(op, **kw)) == C.MARK_KEYS[op]
    for bad in ({"op": "judge"}, {**j, "extra": 1}, {"op": "nope"}, {**C.governance_mark("execute", case="c", rule="decision", basis=[]), "rule": "emergency"}):
        with pytest.raises(ValueError):
            C.check_mark(bad)


def _ok(**b):
    return CallResult("OK", b)


def test_low_forms_accept_and_reject():
    chk = D.check_low_result
    chk("read_object", _ok(ref="Part:P1", props={"n": 1}))
    chk("read_object", CallResult("INVALID", {"reason": "not_found"}))
    chk("list_objects", _ok(refs=["Part:A", "Part:B"]))
    chk("list_objects", CallResult("INVALID", {"reason": "unknown_type"}))
    chk("list_links", _ok(out=["Part:A"], **{"in": []}))
    chk("query", _ok(value=None))
    chk("subscribe", _ok(sub="s1"))
    ev = {"seq": 3, "tick": 1, "kind": "update", "ref": "Part:A", "props": {"n": 2}}
    lk = {"seq": 4, "tick": 1, "kind": "link", "link": ["lt", "Part:A", "Part:B"], "props": {}}
    chk("poll", _ok(events=[ev, lk]))
    dec = {k: 1 for k in D.DECISION_KEYS} | {"subject": D.marker("actor")}
    chk("prov_decision", _ok(partial=True, decision=dec))
    chk("prov_object", _ok(partial=True, decisions=["d1"]))
    chk("prov_decision", CallResult("INVALID", {"reason": "unknown_decision"}))
    aua = dict(partial=True, on_behalf_of=None, path=["e1", D.marker("edge")], authority_version={"redacted": "digest"}, world_seq=3, tick=2)
    chk("authority_used_as", _ok(**aua))
    negatives = [
        ("read_object", _ok(ref="Part:P1", props={}, extra=1)), ("read_object", CallResult("DENIED", {"reason": "forbidden"})),
        ("read_object", CallResult("INVALID", {"reason": "not_found", "detail": "x"})),
        ("list_objects", _ok(refs=["Part:B", "Part:A"])), ("list_objects", CallResult("INVALID", {"reason": "not_found"})),
        ("list_links", _ok(out=[])), ("subscribe", _ok(sub=1)),
        ("poll", _ok(events=[{**ev, "extra": 1}])), ("poll", _ok(events=[lk, ev])), ("poll", _ok(events=[{**ev, "kind": "x"}])),
        ("poll", _ok(events=[{**lk, "ref": "a:b"}])),
        ("prov_decision", _ok(partial=False, decision=dec)), ("prov_decision", _ok(partial=True, decision={"decision_id": 1})),
        ("prov_decision", _ok(partial=True, decision=dec | {"subject": {"redacted": "who"}})),
        ("prov_object", _ok(decisions=[])),
        ("authority_used_as", _ok(**{**aua, "authority_version": "abc"})), ("authority_used_as", _ok(**{**aua, "partial": False})),
        ("authority_used_as", _ok(**{**aua, "path": [D.marker("actor")]})), ("authority_used_as", _ok(**{**aua, "extra": 1})),
        ("nonsense", _ok()),
    ]
    for m, r in negatives:
        with pytest.raises(ValueError):
            chk(m, r)


def test_marker_helpers():
    assert D.marker("digest") == {"redacted": "digest"} and D.is_marker({"redacted": "edge"})
    assert not D.is_marker({"redacted": "edge", "x": 1}) and not D.is_marker("system") and not D.is_marker(None)
    with pytest.raises(ValueError):
        D.marker("who")


def test_mutants_validate_new_names_and_reject_unknown():
    assert mutants.KNOWN["H25"] == ["precedence_inverted", "quorum_weakened", "emergency_no_expiry", "merit_autofill",
                                    "domain_privilege_branch"]
    assert mutants.KNOWN["H26"] == ["existence_status_split", "error_detail_leak", "hidden_tool_schema",
                                    "provenance_edge_retained", "subscription_unfiltered", "redaction_fabrication"]
    assert mutants.validate(mutants.KNOWN["H25"] + mutants.KNOWN["H26"]) >= {"redaction_fabrication", "merit_autofill"}
    with pytest.raises(ValueError):
        mutants.validate(["domain_privilege"])


def test_g3_call_labels_missing_method_unsupported():
    class Old:
        pass
    for m in G3_METHODS:
        with pytest.raises(NotImplementedError, match="not implemented yet - G3"):
            g3_call(Old(), m)
    assert G3_MISSING == "not implemented yet - G3"
    with pytest.raises(ValueError):
        g3_call(Old(), "call_tool")
    assert g3_call(type("N", (), {"poll": lambda self, t, s: 5})(), "poll", "t", "s") == 5
