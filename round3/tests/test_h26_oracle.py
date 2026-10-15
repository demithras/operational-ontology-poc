"""H26 oracle unit tests: disclosure lattice (PROT-H26 s1-s4), canonical low projection (s6), canaries."""
import copy
import json
from pathlib import Path

import pytest

from r3_oracle import disclosure as D, disclosure_prov as P, disclosure_reads as R, lowproj
from r3_shared.disclosure import marker
from r3_shared.variant import CallResult

ROOT = Path(__file__).resolve().parents[1]


def load(dom):
    return (json.loads((ROOT / f"spec/ops/{dom}.json").read_text()), json.loads((ROOT / f"spec/authority/{dom}.v3.json").read_text()))


def snap_of(ops):
    return {"objects": {f"{o['type']}:{o['key']}": {"props": o["props"], "version": 1} for o in ops["seed"]["objects"]},
            "links": [[l["link_type"], l["src"], l["dst"]] for l in ops["seed"]["links"]]}


def mini(auth_extra=None, rules=(), public=("Pub",), plinks=()):
    ops = {"resource_types": [{"name": t, "key_field": "id", "fields": [{"name": "id", "type": "string"}, {"name": "a", "type": "string"}, {"name": "b", "type": "string"}]} for t in ("Pub", "Sec", "Kid")],
           "link_types": [{"name": "L", "from": "Sec", "to": "Kid"}], "operations": [], "reads": []}
    auth = {"principals": [{"id": "u", "roles": ["r"], "relations": [], "delegated_by": None}, {"id": "v", "roles": [], "relations": [], "delegated_by": None}],
            "grants": [], "delegations": [],
            "disclosure": {"public_types": list(public), "public_links": list(plinks), "rules": list(rules)}}
    snap = {"objects": {"Pub:p": {"props": {"id": "p", "a": "A", "b": "B"}, "version": 1},
                        "Sec:s": {"props": {"id": "s", "a": "SA", "b": "SB"}, "version": 1},
                        "Kid:k": {"props": {"id": "k", "a": "KA", "b": "KB"}, "version": 1}}, "links": [["L", "Sec:s", "Kid:k"]]}
    return ops, auth, snap


def rule(rid, t, fields, effect="allow", sel=None, via=None, links=(), exists=True, prov="none"):
    return {"id": rid, "effect": effect, "principal": sel or {"role": "r"}, "object": {"type": t, "keys": None, "via": via},
            "reveals": {"exists": exists, "fields": fields, "links": list(links), "provenance": prov}}


def test_public_types_fully_visible_hidden_is_absent():
    ops, au, sn = mini()
    lv = D.low_view(sn, au, "u", ops)
    assert lv.objects == {"Pub:p": {"id": "p", "a": "A", "b": "B"}}
    assert "Sec:s" not in lv.objects and lv.links == set()


def test_field_subset_and_deny_override_hidden_fields_absent_not_null():
    ops, au, sn = mini(rules=[rule("a1", "Sec", ["id", "a", "b"], links=["L"]), rule("d1", "Sec", ["b"], effect="deny", exists=False)])
    lv = D.low_view(sn, au, "u", ops)
    assert lv.objects["Sec:s"] == {"id": "s", "a": "SA"}
    assert "b" not in lv.objects["Sec:s"]
    assert D.low_view(sn, au, "v", ops).objects.get("Sec:s") is None


def test_via_rule_needs_visible_via_object_least_fixpoint():
    via = {"link": "L", "dir": "in", "type": "Sec"}
    ops, au, sn = mini(rules=[rule("k", "Kid", "*", via=via), rule("s", "Sec", ["id"])])
    lv = D.low_view(sn, au, "u", ops)
    assert set(lv.objects) == {"Pub:p", "Sec:s", "Kid:k"}  # Sec visible first, then Kid through it
    ops2, au2, sn2 = mini(rules=[rule("k", "Kid", "*", via=via)])
    assert "Kid:k" not in D.low_view(sn2, au2, "u", ops2).objects  # via object hidden -> not covered


def test_link_visibility_needs_both_endpoints_and_a_revealing_rule():
    ops, au, sn = mini(rules=[rule("s", "Sec", ["id"], links=["L"]), rule("k", "Kid", ["id"])])
    assert D.low_view(sn, au, "u", ops).links == {("L", "Sec:s", "Kid:k")}
    ops, au, sn = mini(rules=[rule("s", "Sec", ["id"]), rule("k", "Kid", ["id"])])
    assert D.low_view(sn, au, "u", ops).links == set()
    ops, au, sn = mini(rules=[rule("s", "Sec", ["id"], links=["L"])])
    assert D.low_view(sn, au, "u", ops).links == set()  # Kid hidden


def test_existence_deny_hides_object():
    ops, au, sn = mini(rules=[rule("a", "Sec", "*"), rule("d", "Sec", [], effect="deny", exists=True)])
    assert "Sec:s" not in D.low_view(sn, au, "u", ops).objects


@pytest.mark.parametrize("dom", ["project", "manufacturing"])
def test_fixture_low_views_are_deterministic_and_principal_specific(dom):
    ops, au = load(dom)
    sn = snap_of(ops)
    docs = {p["id"]: json.dumps(D.low_view(sn, au, p["id"], ops).to_doc(), sort_keys=True) for p in au["principals"]}
    assert len(set(docs.values())) > 2
    assert docs == {p["id"]: json.dumps(D.low_view(copy.deepcopy(sn), au, p["id"], ops).to_doc(), sort_keys=True) for p in au["principals"]}


@pytest.mark.parametrize("dom", ["project", "manufacturing"])
def test_interp1_alternative_reading_would_kill_fixture_via_rules(dom):
    """INTERP-1 evidence (reported, not chosen silently): PROT-H26 s1.2 covers a via rule when a link CONNECTS the objects;
    s2.1 says "through visible links". Under the second reading some frozen-fixture via rules would never fire (their link type
    is revealed by no rule). The oracle follows s1.2; this test pins how many via rules differ so a ruling can be applied."""
    ops, au = load(dom)
    sn = snap_of(ops)
    dead = set()
    for p in au["principals"]:
        lv = D.low_view(sn, au, p["id"], ops)
        pr = D.principal(au, p["id"])
        for r in au["disclosure"]["rules"]:
            v = r["object"].get("via")
            if v is None or not _sel_ok(r, pr):
                continue
            for ref in [x for x in lv.objects if _covers_via(r, x, sn, lv)]:
                if not any(lt == v["link"] and ref in (a, b) for (lt, a, b) in lv.links):
                    dead.add(r["id"])
    assert dead == EXPECTED_DIFFERENT[dom]


EXPECTED_DIFFERENT = {"project": {"p-researcher-rival", "p-researcher-prediction"}, "manufacturing": set()}


def _sel_ok(r, pr):
    s = r["principal"]
    return s.get("any") or s.get("role") in pr["roles"] or s.get("id") == pr["id"]


def _covers_via(r, ref, sn, lv):
    if ref.split(":", 1)[0] != r["object"]["type"] or r["effect"] != "allow":
        return False
    v = r["object"]["via"]
    for (lt, a, b) in sn["links"]:
        if lt == v["link"] and ((v["dir"] == "in" and b == ref and a in lv.objects) or (v["dir"] == "out" and a == ref and b in lv.objects)):
            return True
    return False


def test_act_implies_exists_gives_existence_not_fields():
    ops, au = load("manufacturing")
    sn = snap_of(ops)
    lv = D.low_view(sn, au, "planner-1", ops)
    assert lv.acted_on and all(r in lv.objects for r in lv.acted_on)


def test_edge_visibility_path_and_below():
    edges = {"e1": {"id": "e1", "issuer": "a", "child": "b", "parent": None}, "e2": {"id": "e2", "issuer": "b", "child": "c", "parent": "e1"},
             "e3": {"id": "e3", "issuer": "c", "child": "d", "parent": "e2"}}
    vis = lambda e, o: P.edge_visible(edges, e, o)  # noqa: E731
    assert vis("e2", "a") and vis("e2", "d") and vis("e2", "b") and vis("e2", "c")
    assert vis("e1", "d") and not vis("e1", "zed")
    assert vis("e3", "a")  # a issued the root of e3's path


def test_decision_views_own_vs_foreign_and_markers():
    ops, au, sn = mini(rules=[rule("s", "Sec", ["id"], prov="scalars")])
    sc = {k: f"v-{k}" for k in ("decision_id", "kind", "operation", "status", "reason")} | {
        "subject": "u", "on_behalf_of": None, "args_digest": "AD", "effect_digest": "ED", "world_seq": 3, "tick": 1, "authority_path": []}
    d = {"id": "d1", "rid": "d1", "subject": "w", "on_behalf_of": None, "approver": None, "resources": ["Sec:s"], "args_refs": ["Sec:s"],
         "args_scalar_free": True, "scalars": {**sc, "subject": "w"}, "effects": [{"kind": "update", "ref": "Sec:s", "changes": {"a": ["x", "y"]}}], "edge_path": []}
    lv = D.low_view(sn, au, "u", ops, D.Facts(decisions=[d]))
    v = P.expected_decision(lv, d)
    assert v["subject"] == marker("actor") and v["args_digest"] == "AD" and v["effect_digest"] == marker("digest")  # 'a' hidden
    assert P.expected_prov_decision(lv, "nope") == ("INVALID", {"reason": "unknown_decision"})
    own = D.low_view(sn, au, "w", ops, D.Facts(decisions=[d]))
    assert P.expected_decision(own, d)["subject"] == "w"
    assert P.expected_decision(D.low_view(sn, au, "v", ops, D.Facts(decisions=[d])), d) is None  # v sees no Sec


def test_canaries_found_everywhere_and_scan_hits():
    body = {"a": ["cv-0123456789ab", 7_000_123, 5], "ck-deadbeef": {"x": True}}
    assert R.canaries_of(body) == {"cv-0123456789ab", 7_000_123, "ck-deadbeef"}
    assert R.scan_hits(body, {"cv-0123456789ab"}) == ["cv-0123456789ab"] and R.scan_hits(body, {"cv-ffffffffffff"}) == []


def test_projection_one_byte_change_diverges_volatile_renames_empty_list_has_no_divergence_but_evaluator_guard():
    a = [lowproj.project("poll", "OK", {"events": []})]
    b = [lowproj.project("poll", "OK", {"events": [], "x": 1})]
    assert lowproj.diff(a, b)["index"] == 0 and lowproj.diff(a, a) is None
    r1, r2 = lowproj.Renamer(), lowproj.Renamer()
    assert lowproj.project("approve", "OK", {"decision_id": "u-1"}, r1) == lowproj.project("approve", "OK", {"decision_id": "u-2"}, r2)
    assert lowproj.project("poll", "OK", {"decision_id": "u-1"}, r1) != lowproj.project("poll", "OK", {"decision_id": "u-2"}, r2)
    assert lowproj.diff([], [b[0]])["length"] == [0, 1]
    assert lowproj.project_result("read_object", CallResult("OK", {"ref": "T:k", "props": {}})) == lowproj.project("read_object", "OK", {"ref": "T:k", "props": {}})
