"""P7a regression: R-3 governs creates only; every UPDATE effect writes exactly the fields the ops-spec effect lists."""
import pytest

UPDATES = [("edit_threshold", {"threshold": "T-A", "value": {"min": 11}}),
           ("preregister_hypothesis", {"hypothesis": "H-A", "freeze_hash": "a" * 64}),
           ("start_run", {"hypothesis": "H-B"}),
           ("evaluate_hypothesis", {"hypothesis": "H-C"}),
           ("supersede_hypothesis", {"hypothesis": "H-D", "successor": "H-E"}),
           ("flag_orphan_component", {"component": "cmp-orphan"})]


def _update_effects(proj, op):
    o = next(o for o in proj.ops["operations"] if o["name"] == op)
    return [e for e in o["effects"] if e["kind"] == "update"]


def test_every_spec_update_effect_is_covered():
    from r3_shared.opsspec import load_ops_spec
    spec = {(o["name"]) for o in load_ops_spec("project")["operations"] if any(e["kind"] == "update" for e in o["effects"])}
    assert spec == {op for op, _ in UPDATES}


@pytest.mark.parametrize("op,args", UPDATES)
@pytest.mark.parametrize("via", ["direct", "tool"])
def test_update_writes_exactly_the_spec_fields(proj, op, args, via):
    f = proj.dep.direct if via == "direct" else proj.dep.call_tool
    before = proj.snap()
    res, eff = proj.effects_of(lambda: f(proj.token("researcher-1"), op, args, request_id="u1"))
    assert res.status == "OK", res
    after = proj.snap()
    for e in _update_effects(proj, op):
        want = set(e["props"])
        upd = [x for x in eff if x["kind"] == "update" and x["ref"].startswith(e["type"] + ":")]
        assert len(upd) == 1, eff
        assert set(upd[0]["changes"]) <= want, upd  # nothing outside the spec's fields
        assert want <= set(after["objects"][upd[0]["ref"]]["props"]), (op, want)  # every spec field is present
        assert all(k in before["objects"][upd[0]["ref"]]["props"] or k in upd[0]["changes"] for k in want)


def test_preregister_writes_freeze_hash_and_phase(proj):
    assert proj.dep.direct(proj.token("researcher-1"), "preregister_hypothesis",
                           {"hypothesis": "H-A", "freeze_hash": "b" * 64}, request_id="u2").status == "OK"
    p = proj.snap()["objects"]["Hypothesis:H-A"]["props"]
    assert p["freeze_hash"] == "b" * 64 and p["phase"] == "PREREGISTERED"
