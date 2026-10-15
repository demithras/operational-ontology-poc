"""Protocol-level tests of the Gate 3 surface on the FAKE deployment (the reference behaviour sufficient for the forms)
+ the registry conformance rule for the real variants (missing methods surface as G3 NotImplementedError)."""
import pytest

from r3_shared import constitutional as C
from r3_shared import disclosure as D
from r3_shared.authspec import load_auth_spec
from r3_shared.clock import LogicalClock
from r3_shared.governance import load_governance
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.registry import VARIANTS, load_variant
from r3_shared.variant import G3_METHODS, Variant, g3_call
from r3_shared.world import WorldStore
from tests.fakes.fake_variant import FakeDeployment, FakeVariant


def _dep(tmp_path, governance="collegial", dom="manufacturing"):
    clock = LogicalClock()
    idp, st = IdentityProvider("secret-secret"), WorldStore(tmp_path / "w.db", clock=clock)
    gov = load_governance(governance, dom) if governance else None
    dep = FakeVariant().deploy(dom, st.handle_factory(), idp.verifier(), load_ops_spec(dom), load_auth_spec(dom), clock,
                               state_dir=str(tmp_path), governance=gov)
    return dep, idp, st, clock


def _tok(idp, who="planner-1"):
    return idp.issue(who, "fake", 10_000, LogicalClock())


def test_fake_has_every_g3_method():
    assert all(callable(getattr(FakeDeployment, m)) for m in G3_METHODS)


def test_no_governance_and_check_order(tmp_path):
    dep, idp, st, _ = _dep(tmp_path, governance=None)
    t = _tok(idp)
    act = {"kind": "appeal", "case": "c1"}
    r = dep.constitutional("bad-token", act, "r0")
    assert (r.status, r.body) == ("DENIED", {"reason": "token"})  # token first
    r = dep.constitutional(t, {"kind": "appeal"}, "r1")
    assert (r.status, r.body) == ("INVALID", {"reason": "schema"})  # schema before no_governance
    r = dep.constitutional(t, act, "r2")
    assert (r.status, r.body) == ("INVALID", {"reason": "no_governance"})
    assert [r for r in st.reader().log() if r["kind"] == "mark"] == []  # refusals write nothing
    dep.set_governance(load_governance("collegial", "manufacturing"))
    r = dep.constitutional(t, act, "r3")
    assert (r.status, r.body) == ("INVALID", {"reason": "unknown_case"})


def test_ok_actions_write_exactly_one_governance_mark_each(tmp_path):
    dep, idp, st, _ = _dep(tmp_path)
    t = _tok(idp)
    plan = [("propose", {"kind": "propose", "case": "c1", "operation": "reschedule_work_order", "args": {"work_order_id": "WO-42"}, "on_behalf_of": None}),
            ("judge", {"kind": "judge", "case": "c1", "stage": "decision", "value": "concur", "merit": "ok"}),
            ("appeal", {"kind": "appeal", "case": "c1"}), ("execute", {"kind": "execute", "case": "c1"})]
    for i, (op, a) in enumerate(plan):
        r = dep.constitutional(t, a, f"rid-{i}")
        assert r.status == "OK", (op, r)
        txs = {}
        for row in st.reader().log():
            txs.setdefault(row["tx"], []).append(row)
        last = txs[max(txs)]
        gm = [x for x in last if x["kind"] == "mark" and x["ref"] == "governance"]
        assert len(gm) == 1 and gm[0]["data"]["op"] == op
        C.check_mark(gm[0]["data"])
    assert dep.case_state("c1")["executed"] is True and dep.case_state("nope") is None
    n = len([x for x in st.reader().log() if x["ref"] == "governance"])
    assert dep.constitutional(t, plan[0][1], "rid-0").status == "OK"  # request_id idempotent: stored result
    assert len([x for x in st.reader().log() if x["ref"] == "governance"]) == n


def test_crash_points_apply_to_constitutional(tmp_path):
    dep, idp, st, _ = _dep(tmp_path)
    t = _tok(idp)
    a = {"kind": "propose", "case": "c9", "operation": "o", "args": {}, "on_behalf_of": None}
    dep.arm_crash("before_commit")
    assert dep.constitutional(t, a, "x1").status == "UNKNOWN"
    assert dep.constitutional(t, a, "x1").status == "UNAVAILABLE"
    assert [r for r in st.reader().log() if r["ref"] == "governance"] == []


def test_low_channels_return_frozen_forms(tmp_path):
    dep, idp, st, clock = _dep(tmp_path)
    t = _tok(idp)
    h = st.handle("fake-service")
    h.create("Part", "P1", {"n": 1})
    h.create("Part", "P2", {"n": 2})
    h.link("L", "Part:P1", "Part:P2")
    sub = dep.subscribe(t, {"types": ["Part"]})
    D.check_low_result("subscribe", sub)
    h.update("Part", "P1", {"n": 5})
    h.create("Part", "P3", {"n": 3})
    for method, res in [("read_object", dep.read_object(t, "Part:P1")), ("read_object", dep.read_object(t, "Part:ZZ")),
                        ("list_objects", dep.list_objects(t, "Part")), ("list_objects", dep.list_objects(t, "Nope")),
                        ("list_links", dep.list_links(t, "Part:P1", "L")), ("query", dep.query(t, "count", {"type": "Part"})),
                        ("poll", dep.poll(t, sub.body["sub"])), ("prov_decision", dep.prov_decision(t, "nope")),
                        ("authority_used_as", dep.authority_used_as(t, "nope")), ("prov_object", dep.prov_object(t, "Part:P1"))]:
        D.check_low_result(method, res)
    assert dep.read_object(t, "Part:P1").body == {"ref": "Part:P1", "props": {"n": 5}}
    assert dep.list_links(t, "Part:P1", "L").body == {"out": ["Part:P2"], "in": []}
    kinds = {e["ref"]: e["kind"] for e in dep.poll(t, sub.body["sub"]).body["events"]}
    assert kinds == {}  # events are delivered once per poll
    # legacy read() is redefined onto the P1e-5 forms (ruling Q12)
    assert dep.read(t, "get", {"type": "Part", "key": "P2"}).body == {"ref": "Part:P2", "props": {"n": 2}}
    assert dep.read(t, "list", {"type": "Part"}).body == {"refs": ["Part:P1", "Part:P2", "Part:P3"]}
    assert dep.read(t, "get", {"type": "Part", "key": "none"}).body == {"reason": "not_found"}


def test_poll_event_content(tmp_path):
    dep, idp, st, _ = _dep(tmp_path)
    t = _tok(idp)
    h = st.handle("fake-service")
    s = dep.subscribe(t, {"types": ["Part"]}).body["sub"]
    h.create("Part", "A", {"n": 1})
    h.update("Part", "A", {"n": 2})
    ev = dep.poll(t, s).body["events"]
    assert [(e["kind"], e["ref"], e["props"]) for e in ev] == [("create", "Part:A", {"n": 2})]  # coalesced between polls
    h.delete("Part", "A")
    ev = dep.poll(t, s).body["events"]
    assert [(e["kind"], e["ref"]) for e in ev] == [("delete", "Part:A")]
    for e in ev:
        D.check_event(e)


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_registered_variants_g3_surface_is_present_or_not_implemented(name):
    """Real variants need not have the Gate 3 methods until their builders land; a missing method must surface as
    NotImplementedError("not implemented yet - G3") through g3_call (never AttributeError, never a fake success)."""
    try:
        v = load_variant(name)
    except NotImplementedError as exc:
        assert "not implemented yet" in str(exc)
        return
    assert isinstance(v, Variant)
    cls = v.deployment_class
    for m in G3_METHODS:
        if callable(getattr(cls, m, None)):
            continue
        with pytest.raises(NotImplementedError, match="not implemented yet - G3"):
            g3_call(object.__new__(cls), m)
