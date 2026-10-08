"""G3 fix5 (paladin): G3-E24 R5 act replay, basis once per judgment, G3-E26 public-type provenance + INTERP-2, G3-E27 reply reason
and own-refused authority_used_as, RC6 read facts, rule-order independence, update effect rows (props | patch)."""
import itertools
from types import SimpleNamespace

import pytest

from g2_rig import new_anchor
from g3_rig import G3Rig
from paladin.procedure import CaseBook
from paladin.sovview import LowView, low_view
from r3_shared.histstore import HistoryStore

THR = ("edit_threshold", {"threshold": "T-A", "value": {"min": 12}})


# ---- H25 RC5: replay of an emergency act re-evaluates the emergency, not base authority -------------------------------
def _emergency(tmp_path, expires=5):
    r = G3Rig(tmp_path)
    r.propose("admin-1", "d1", "emergency:declare", {"emergency": "e", "scope": {"operations": ["edit_threshold"],
              "resources": [{"type": "Threshold", "keys": None}]}, "expires_at": expires, "grantees": ["researcher-1"]})
    r.judge("agent-draft-1", "d1", "concur")
    return r


def test_act_replay_in_the_active_emergency_returns_the_stored_result(tmp_path):
    r = _emergency(tmp_path)
    first = r.act("researcher-1", "act", rid="a1", emergency="e", operation=THR[0], args=THR[1])
    assert first.status == "OK"
    again, eff = r.effects_of(lambda: r.act("researcher-1", "act", rid="a1", emergency="e", operation=THR[0], args=THR[1]))
    assert again.status == "OK" and not eff and again.body.get("replayed") is True


def test_act_replay_after_expiry_is_refused_by_the_emergency_not_base_authority(tmp_path):
    r = _emergency(tmp_path)
    assert r.act("researcher-1", "act", rid="a1", emergency="e", operation=THR[0], args=THR[1]).status == "OK"
    r.adv(10)
    res, eff = r.effects_of(lambda: r.act("researcher-1", "act", rid="a1", emergency="e", operation=THR[0], args=THR[1]))
    assert res.status == "DENIED" and res.body == {"reason": "emergency_expired"} and not eff


# ---- H25 RC6: a judge in two bodies is one counted judgment ----------------------------------------------------------------
def test_basis_lists_each_judgment_once_in_seq_order():
    js = {"b1": {"x": {"rid": "r2", "seq": 5}, "y": {"rid": "r1", "seq": 3}}, "b2": {"x": {"rid": "r2", "seq": 5}}}
    stub = SimpleNamespace(bodies=lambda c: ["b1", "b2"], counted=lambda c, st, b: js[b], review_body=lambda c: None)
    c = SimpleNamespace(decided={"decision": ("ALLOW", 1, 1, "judge")})
    assert CaseBook.basis(stub, c, "decision") == ["r1", "r2"]


# ---- H26 RC4: public types carry provenance level `none` (G3-E26) ---------------------------------------------------------
def _disc(rules, public=()):
    return {"public_types": list(public), "public_links": [], "rules": rules}


def _rule(effect, t, fields="*", prov="none", links=()):
    return {"effect": effect, "principal": {"any": True}, "object": {"type": t, "keys": None, "via": None},
            "reveals": {"exists": effect == "allow", "fields": fields, "links": list(links), "provenance": prov}}


OBS = {"id": "o", "roles": [], "relations": []}
OBJS = {"Part:p": {"a": 1, "b": 2}}


def test_public_type_has_provenance_none():
    v = low_view(_disc([], public=["Part"]), OBS, OBJS, set(), set())
    assert v.level["Part:p"] == "none" and v.objects["Part:p"] == {"a": 1, "b": 2}


# ---- H26 RC6c: rule order does not matter (union allow - union deny) ----------------------------------------------------
@pytest.mark.parametrize("order", list(itertools.permutations(range(3))))
def test_rule_order_independent(order):
    rs = [_rule("allow", "Part", fields=["a", "b"], prov="actors", links=["L"]),
          _rule("deny", "Part", fields=["b"], prov="scalars", links=["L"]),
          _rule("allow", "Part", fields=["a"], prov="scalars", links=["M"])]
    v = low_view(_disc([rs[i] for i in order]), OBS, OBJS, set(), set())
    assert v.objects["Part:p"] == {"a": 1} and v.level["Part:p"] == "none" and v.linkable["Part:p"] == {"M"}


def test_deny_with_level_none_keeps_the_allowed_level():
    rs = [_rule("deny", "Part", fields=["b"], prov="none"), _rule("allow", "Part", fields=["a"], prov="actors")]
    for o in (rs, rs[::-1]):
        assert low_view(_disc(o), OBS, OBJS, set(), set()).level["Part:p"] == "actors"


# ---- G3-E26/27 provenance views --------------------------------------------------------------------------------------------
ATT = ("attach_evidence", {"hypothesis": "H-C", "evidence": "EV-C1"})


@pytest.fixture
def rig(tmp_path_factory):
    ap = new_anchor(tmp_path_factory.mktemp("anchor"))
    tmp = tmp_path_factory.mktemp("rig")
    r = G3Rig(tmp, v3=True, history=HistoryStore(str(tmp / "h.sqlite")), anchor=ap.client())
    yield r
    ap.close()


def _view(fields):
    v = LowView()
    for ref, fs in fields.items():
        v.objects[ref] = {f: 0 for f in fs}
        v.fields_of[ref] = frozenset(fs)
        v.level[ref] = "scalars"
    return v


def test_args_low_needs_visible_refs_and_no_scalar_inputs(rig):
    core = rig.dep._c
    rec = {"s": {"subject": "someone", "on_behalf_of": None}, "refs": [["Part", "p"]], "flows": [["Part", "a"]], "sc": True}
    assert core._args_low("viewer-1", rec, _view({"Part:p": {"a"}})) is False      # scalar flows into a VISIBLE field: still not low
    rec2 = {**rec, "flows": [], "sc": False}
    assert core._args_low("viewer-1", rec2, _view({"Part:p": {"a"}})) is True       # refs only, all existence-visible
    assert core._args_low("viewer-1", rec2, _view({})) is False                     # a hidden ref
    own = {**rec, "s": {"subject": "viewer-1", "on_behalf_of": None}}
    assert core._args_low("viewer-1", own, _view({})) is True                       # own


def test_update_effect_rows_record_props_and_patch_fields(rig):
    core = rig.dep._c
    d = {"rid": "u1", "kind": "direct", "sub": "viewer-1", "obo": None, "op": "no_such_op", "args": {}, "status": "OK",
         "reason": "ok", "world_seq": 1, "tick": 1, "path": [], "ops_spec": core.ops_spec, "doc": core.auth, "evidence": [],
         "rows": [{"kind": "update", "ref": "Component:c", "data": {"props": {"id": 1, "orphan": 2}, "patch": {"orphan": 2}}},
                  {"kind": "update", "ref": "Component:d", "data": {"patch": {"zed": 1}}}]}
    core.note_decision(d)
    rec = core.ledger.get_meta("dec:u1")
    assert rec["rows"] == [{"k": "update", "r": "Component:c", "f": ["id", "orphan"]}, {"k": "update", "r": "Component:d", "f": ["zed"]}]
    # the guard: an observer who sees only `orphan` does not see the digest of an update that wrote {id, orphan}
    assert core._eff_low("viewer-1", rec, _view({"Component:c": {"orphan"}, "Component:d": {"zed"}})) is False
    assert core._eff_low("viewer-1", rec, _view({"Component:c": {"orphan", "id"}, "Component:d": {"zed"}})) is True


def test_view_reason_is_the_public_reply_reason_and_own_refusal_has_a_used_path(rig):
    res = rig.dep.direct(rig.tok("researcher-1"), "attach_evidence", {"hypothesis": "H-NOPE", "evidence": "EV-C1"}, request_id="rf1")
    assert res.status == "DENIED"
    assert rig.dep._c.ledger.get_meta("dec:rf1") is not None                       # a governed (anchored) refusal
    d = rig.dep.prov_decision(rig.tok("researcher-1"), "rf1")
    assert d.body["decision"]["reason"] == res.body["reason"]                        # public reply reason, not the gate code
    used = rig.dep.authority_used_as(rig.tok("researcher-1"), "rf1")
    assert used.status == "OK" and used.body["partial"] is True and used.body["path"] == []
    assert rig.dep.authority_used_as(rig.tok("viewer-1"), "rf1").status != "OK"      # not own -> unknown, like prov_decision
    ok = rig.dep.direct(rig.tok("researcher-1"), *ATT, request_id="d1")
    assert ok.status == "OK"
    assert rig.dep.prov_decision(rig.tok("researcher-1"), "d1").body["decision"]["reason"] == "ok"


# ---- H26 RC6a/b: reads over the low view degrade like null, never raise or guess ------------------------------------------
def test_latest_experiment_with_hidden_version_does_not_raise(monkeypatch):
    from paladin.domains.project.logic import facts
    props = {"E1": {"id": "E1"}, "E2": {"id": "E2", "version": "2"}}
    monkeypatch.setattr(facts, "experiments_of", lambda view, hid: ["E1", "E2"])
    monkeypatch.setattr(facts, "props", lambda view, t, k: props[k])
    assert facts.latest_experiment(None, "H") == "E2"          # a hidden version sorts as null (lowest)
    props["E2"] = {"id": "E2"}
    assert facts.latest_experiment(None, "H") in ("E1", "E2")   # all hidden: still no exception


def test_work_order_requirement_without_a_visible_part_link_is_skipped(monkeypatch):
    from paladin.domains.manufacturing.logic import facts
    view = SimpleNamespace(get=lambda t, k: {"props": {"status": "OPEN"}},
                           follow=lambda *a, **k: [{"key": "b1", "props": {"quantity": 80}}])
    monkeypatch.setattr(facts, "_one", lambda *a, **k: None)
    assert facts.work_order(view, "wo")["requirements"] == {}


def test_query_has_no_catch_all():
    import inspect
    from paladin.sovchan import SovMixin
    src = inspect.getsource(SovMixin.query)
    assert "except Exception" not in src and "query_error" not in src
