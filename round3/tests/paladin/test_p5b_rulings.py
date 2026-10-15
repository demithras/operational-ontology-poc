"""P5b: orchestrator rulings R-1..R-4 pinned on the Paladin variant (effects measured from the world store)."""
import copy

import pytest

TR = {"source_warehouse": "WH-A", "destination_warehouse": "WH-B", "part": "PX-17", "quantity": 5}
RES = "researcher-1"


def _created(eff):
    return {e["ref"]: e.get("props", {}) for e in eff if e["kind"] == "create"}


def _spec_fields(rig, op, typ):
    o = next(o for o in rig.ops["operations"] if o["name"] == op)
    return {k for e in o["effects"] if e["kind"] == "create" and e["type"] == typ for k in e["props"]}


# ---- R-3: a create writes exactly the spec fields (key is the object key, not a property) ----------------------
CREATES = [("create_hypothesis", {"claim": "brand new claim"}, ["Hypothesis"]),
           ("new_experiment_version", {"experiment": "E-C@v1", "contract_version": "CV-1"}, ["Experiment", "ContractVersion"]),
           ("attach_evidence", {"hypothesis": "H-F", "evidence": "EV-C2"}, []),
           ("evaluate_hypothesis", {"hypothesis": "H-C"}, ["Verdict"]),
           ("record_decision", {"decision": "DEC-1", "contract_version": "CV-1"}, [])]


@pytest.mark.parametrize("op,args,types", CREATES)
@pytest.mark.parametrize("via", ["direct", "tool"])
def test_r3_creates_write_exactly_spec_fields(proj, op, args, types, via):
    f = proj.dep.direct if via == "direct" else proj.dep.call_tool
    res, eff = proj.effects_of(lambda: f(proj.token(RES), op, args, request_id="r3"))
    assert res.status == "OK", res
    made = _created(eff)
    assert len(made) == len(types)
    for ref, props in made.items():
        typ = ref.split(":", 1)[0]
        assert set(props) == _spec_fields(proj, op, typ), (ref, props)


def test_r3_upsert_creates_are_not_rewritten_with_extra_props(proj):
    # Evidence/Decision already exist in the seed: re-attaching must not add properties either
    res, eff = proj.effects_of(lambda: proj.dep.direct(proj.token(RES), "record_decision",
                                                       {"decision": "DEC-1", "contract_version": "CV-1"}, request_id="r3"))
    assert res.status == "OK" and all(e["kind"] == "link" for e in eff)


# ---- R-1: logical-time ordering: head_commit is the numerically latest Commit ------------------------------------
def test_r1_head_commit_is_c0ffee0001_on_the_seed(proj):
    res, eff = proj.effects_of(lambda: proj.dep.direct(proj.token(RES), "new_experiment_version",
                                                       {"experiment": "E-C@v1", "contract_version": "CV-1"}, request_id="r1"))
    assert res.status == "OK"
    assert _created(eff)["ContractVersion:CV-1+2"]["git_commit"] == "c0ffee0001"  # "50" > "100" as strings would pick ...0000


def test_r1_head_commit_follows_numeric_not_string_order(proj):
    svc = proj.store.handle("seed")
    svc.create("Commit", "c0ffee0002", {"committed_at": 9, "message": "later key, earlier tick", "sha": "c0ffee0002"})
    res, eff = proj.effects_of(lambda: proj.dep.direct(proj.token(RES), "new_experiment_version",
                                                       {"experiment": "E-C@v1", "contract_version": "CV-1"}, request_id="r1"))
    assert _created(eff)["ContractVersion:CV-1+2"]["git_commit"] == "c0ffee0001"


# ---- R-2: supplied optional references must resolve --------------------------------------------------------------
@pytest.mark.parametrize("via", ["direct", "tool"])
def test_r2_nonexistent_optional_work_order_is_invalid_with_zero_effects(mfg, via):
    f = mfg.dep.direct if via == "direct" else mfg.dep.call_tool
    res, eff = mfg.effects_of(lambda: f(mfg.token("planner-1"), "transfer_inventory", {**TR, "work_order": "NOPE"}, request_id="r2"))
    assert res.status == "INVALID" and eff == [], (res, eff)


def test_r2_existing_optional_work_order_commits(mfg):
    res, eff = mfg.effects_of(lambda: mfg.dep.direct(mfg.token("planner-1"), "transfer_inventory",
                                                     {**TR, "work_order": "WO-43"}, request_id="r2"))
    assert res.status == "OK" and len(eff) == 1


# ---- R-4: strict shared authority validation on deploy and every set_authority -----------------------------------
def _dup_grant(spec):
    s = copy.deepcopy(spec)
    s["grants"].append(copy.deepcopy(s["grants"][0]))
    return s


def _dangling_delegation(spec):
    s = copy.deepcopy(spec)
    s["principals"][0]["delegated_by"] = "nobody-at-all"
    return s


def _unknown_op_grant(spec):
    s = copy.deepcopy(spec)
    g = copy.deepcopy(s["grants"][0])
    g.update(id="zz-new", origin="neutral", effect="allow", operation="no_such_operation")
    s["grants"].append(g)
    return s


@pytest.mark.parametrize("mutate", [_dup_grant, _dangling_delegation, _unknown_op_grant])
@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_r4_invalid_authority_spec_raises_and_changes_nothing(make_rig, domain, mutate):
    rig = make_rig(domain)
    before_version, before_world = rig.dep.authority_version(), rig.snap()
    with pytest.raises(ValueError):
        rig.dep.set_authority(mutate(rig.auth))
    assert rig.dep.authority_version() == before_version and rig.snap() == before_world
    ok = rig.dep.set_authority(copy.deepcopy(rig.auth))  # the deployment still works and accepts a valid spec
    assert ok is None


@pytest.mark.parametrize("domain", ["manufacturing", "project"])
def test_r4_invalid_authority_spec_rejected_on_deploy(make_rig, domain):
    from r3_shared.authspec import load_auth_spec
    with pytest.raises(ValueError):
        make_rig(domain, auth_spec=_dup_grant(load_auth_spec(domain)))
