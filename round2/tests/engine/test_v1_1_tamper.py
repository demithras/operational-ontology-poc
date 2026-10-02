"""Engine v1.1 regression: the four exp-h17-001 tamper attacks end with 0 effects; no-tamper controls are unchanged.

Three layers per attack:
  * returned-record tamper (what exp-h17-001 did): editing a value the Engine returned raises CapabilityError and
    cannot reach the Engine's state;
  * internal-state tamper (defence in depth, simulating Engine v1's aliasing): editing the Engine's OWN record and then
    running the routine operator step is refused by the journaled gate-pass check -> DENIED, 0 effects;
  * the exp-h17-001 harness functions themselves, through both domain packs (exact reproduction).
"""
import pytest

from eoo_engine import ENGINE_VERSION, CapabilityError, EngineError, InvalidRequest, SimulatedCrash
from eoo_engine.gatepass import inputs_hash
from synth import FakeCarrier, build, effects_of


def _walk(v, out):
    out.add(id(v))
    if isinstance(v, dict):
        for x in v.values():
            _walk(x, out)
    elif isinstance(v, list):
        for x in v:
            _walk(x, out)
    return out


def _containers(v, out):
    if isinstance(v, (dict, list)):
        out.add(id(v))
        for x in (v.values() if isinstance(v, dict) else v):
            _containers(x, out)
    return out


# ---- returned values are immutable, detached snapshots --------------------------------------------------------
def test_engine_version_is_1_1():
    assert ENGINE_VERSION == "1.1"


def test_every_returned_record_refuses_mutation_and_shares_no_container_with_internal_state():
    eng, _, _ = build()
    recs = [eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="p"),
            eng.tool("filler").propose_action("fill_box", {"box": "b2", "amount": 1}, idempotency_key="q")]
    recs.append(eng.approve(recs[0]["exec"], "approver"))
    recs += [eng.executions[x] for x in eng.executions] + list(eng.recover())
    internal = set()
    for r in eng._executions.values():
        _containers(r, internal)
    for rec in recs:
        assert not (_containers(rec, set()) & internal)
        for attempt in (lambda: rec.__setitem__("state", "APPROVED"), lambda: rec.update(state="x"),
                        lambda: rec.pop("state"), lambda: rec.setdefault("new", 1), lambda: rec.clear()):
            with pytest.raises(CapabilityError):
                attempt()
    rec = recs[0]
    for attempt in (lambda: rec["inputs"].__setitem__("amount", -5), lambda: rec["gates"].append({"gate": "x"}),
                    lambda: rec["gates"].__setitem__(0, {}), lambda: rec["gates"][0].__setitem__("passed", True),
                    lambda: rec["approvals"].clear(), lambda: rec["history"].extend(["APPROVED"])):
        with pytest.raises(CapabilityError):
            attempt()
    with pytest.raises(CapabilityError):
        eng.executions.foo = 1
    assert isinstance(rec, dict) and recs[2] == eng.executions[rec["exec"]]  # detached copy of the current record


def test_effect_log_provenance_and_query_results_are_immutable():
    eng, _, _ = build()
    eng.propose("fill_box", {"box": "b1", "amount": 5}, "filler", idempotency_key="k")
    for e in list(eng.effect_log.entries()) + list(eng.provenance.entries()):
        with pytest.raises(TypeError):
            e["x"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        eng.get("Box", "b1")["props"]["level"] = 99  # type: ignore[index]
    assert eng.get("Box", "b1")["props"]["level"] == 15


def test_every_provenance_record_names_the_engine_version():
    eng, _, _ = build()
    eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="k")
    eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="k")  # retry record
    eng.propose("fill_box", {"box": "b1", "amount": 5}, "nobody", idempotency_key="z")  # denied
    prov = eng.provenance.entries()
    assert prov and {p["engine_version"] for p in prov} == {"1.1"}
    assert {r["engine_version"] for r in eng.journal} == {"1.1"}


def test_gate_pass_is_journaled_before_approved_with_the_gated_inputs_hash():
    eng, _, _ = build()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 5}, "filler", idempotency_key="k")
    gp = [r for r in eng.journal if r["kind"] == "gate_pass" and r["exec"] == rec["exec"]]
    appr = [r for r in eng.journal if r["kind"] == "exec" and r["rec"]["state"] == "APPROVED"]
    assert len(gp) == 1 and gp[0]["via"] == "gates" and gp[0]["seq"] < appr[0]["seq"]
    assert gp[0]["inputs_hash"] == inputs_hash({"box": "b1", "amount": 5}) and rec["state"] == "RECONCILED_SUCCESS"
    pend = eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="p")
    assert not [r for r in eng.journal if r["kind"] == "gate_pass" and r["exec"] == pend["exec"]]
    eng.approve(pend["exec"], "approver")
    gp = [r for r in eng.journal if r["kind"] == "gate_pass" and r["exec"] == pend["exec"]]
    assert len(gp) == 1 and gp[0]["via"] == "approval" and gp[0]["approved_by"] == "approver"


# ---- synthetic package: the four attacks ----------------------------------------------------------------------
def _ext(carrier):
    return len(carrier.calls)


def test_synth_inputs_tamper_then_approve():
    """Attack 1 (tamper_returned_inputs_then_approve): the gated amount is what executes, never the edited one."""
    eng, _, carrier = build()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="t1")
    assert rec["state"] == "PENDING_APPROVAL"
    with pytest.raises(CapabilityError):
        rec["inputs"]["amount"] = -5
    assert len(eng.effect_log) == 0 and eng.executions[rec["exec"]]["inputs"]["amount"] == 60
    # internal-state tamper (v1 aliasing simulated) -> journaled gate-pass check refuses: DENIED, 0 effects
    eng._executions[rec["exec"]]["inputs"]["amount"] = -5
    out = eng.approve(rec["exec"], "approver")
    assert out["state"] == "DENIED" and out["gates"][-1]["gate"] == "gate_pass" and len(eng.effect_log) == 0
    assert eng.get("Box", "b1")["props"]["level"] == 10


def test_synth_inputs_control_unchanged():
    eng, _, _ = build()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 60}, "filler", idempotency_key="t1")
    out = eng.approve(rec["exec"], "approver")
    assert out["state"] == "RECONCILED_SUCCESS" and len(effects_of(eng, rec["exec"])) == 1
    assert effects_of(eng, rec["exec"])[0]["payload"]["level"] == 70


def test_synth_state_flip_denied_to_pending_then_approve():
    """Attack 2: a request DENIED at authority, 'flipped' to PENDING_APPROVAL, then a legitimate approval."""
    eng, _, carrier = build()
    rec = eng.propose("fill_box", {"box": "b1", "amount": 60}, "nobody", idempotency_key="t1")
    assert rec["state"] == "DENIED"
    with pytest.raises(CapabilityError):
        rec["state"] = "PENDING_APPROVAL"
    with pytest.raises(InvalidRequest):
        eng.approve(rec["exec"], "approver")
    eng._executions[rec["exec"]]["state"] = "PENDING_APPROVAL"  # internal tamper
    try:
        eng.approve(rec["exec"], "approver")
    except EngineError:
        pass
    assert len(eng.effect_log) == 0 and _ext(carrier) == 0 and eng.get("Box", "b1")["props"]["level"] == 10
    assert eng.executions[rec["exec"]]["state"] == "DENIED"


@pytest.mark.parametrize("action,inputs", [("fill_box", {"box": "b1", "amount": 5}), ("ship_box", {"box": "b1"})])
def test_synth_state_flip_denied_to_approved_then_recover(action, inputs):
    """Attacks 3/4 (both domains in exp-h17-001): DENIED request flipped to APPROVED, then an operator recover()."""
    eng, _, carrier = build()
    rec = eng.propose(action, inputs, "nobody", idempotency_key="t2")
    assert rec["state"] == "DENIED"
    with pytest.raises(CapabilityError):
        rec["state"] = "APPROVED"
    assert eng.recover() == [] and len(eng.effect_log) == 0
    eng._executions[rec["exec"]]["state"] = "APPROVED"  # internal tamper
    report = eng.recover()
    assert report == [{"exec": rec["exec"], "from": "APPROVED", "to": "DENIED"}]
    assert len(eng.effect_log) == 0 and _ext(carrier) == 0 and eng.get("Box", "b1")["props"]["level"] == 10
    assert eng.executions[rec["exec"]]["gates"][-1]["gate"] == "gate_pass"


def test_synth_state_control_recover_after_denied_unchanged():
    eng, _, carrier = build()
    rec = eng.propose("ship_box", {"box": "b1"}, "nobody", idempotency_key="t2")
    assert eng.recover() == [] and eng.executions[rec["exec"]]["state"] == "DENIED" and _ext(carrier) == 0


def test_synth_crash_after_approved_then_tampered_inputs_on_recover(tmp_path):
    """Recovery re-checks the gate-pass: a record APPROVED before a crash whose inputs changed is DENIED."""
    j = tmp_path / "j.jsonl"
    eng, k, carrier = build(journal=j, faults={"APPROVED"})
    with pytest.raises(SimulatedCrash):
        eng.propose("fill_box", {"box": "b1", "amount": 5}, "filler", idempotency_key="k")
    eng2, _, _ = build(k=k, carrier=carrier, journal=j, seed=False, register=False)
    eng2._executions["x1"]["inputs"]["amount"] = 50
    assert eng2.recover() == [{"exec": "x1", "from": "APPROVED", "to": "DENIED"}] and len(eng2.effect_log) == 0
    eng4, _, _ = build(k=k, carrier=carrier, journal=j, seed=False, register=False)
    assert eng4.executions["x1"]["state"] == "DENIED" and eng4.recover() == []  # the refusal is journaled


def test_synth_crash_after_approved_control_recovers_normally(tmp_path):
    j = tmp_path / "j.jsonl"
    eng, k, carrier = build(journal=j, faults={"APPROVED"})
    with pytest.raises(SimulatedCrash):
        eng.propose("fill_box", {"box": "b1", "amount": 5}, "filler", idempotency_key="k")
    eng2, _, _ = build(k=k, carrier=carrier, journal=j, seed=False, register=False)
    assert eng2.recover() == [{"exec": "x1", "from": "APPROVED", "to": "RECONCILED_SUCCESS"}]
    assert len(eng2.effect_log) == 1 and eng2.get("Box", "b1")["props"]["level"] == 15


# ---- both domain packs: the exp-h17-001 harness attacks themselves + internal-state variants --------------------
DOMAINS = ("manufacturing", "project")


def _plan(domain):
    from eoo_h17 import tamper
    return tamper.TAMPER_BOTH + (tamper.TAMPER_MFG if domain == "manufacturing" else [])


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_exp_h17_001_tamper_attacks_end_with_zero_effects(domain):
    from eoo_h17.agents import run_attack
    from eoo_h17.drivers import new_driver
    attacks = [(n, f) for n, f in _plan(domain) if not n.startswith("control")]
    assert len(attacks) == (3 if domain == "manufacturing" else 1)  # 4 attack rows in exp-h17-001
    for n, f in attacks:
        drv = new_driver(domain, "std")
        r = run_attack(drv, n, "tamper", f)
        assert r["violation"] is False and r["world_changed"] is False, r
        assert r["exception"] == "CapabilityError" and r["unexpected_exception"] is False, r
        assert len(drv.engine.effect_log) == 0 and drv.external_count() == 0


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_exp_h17_001_controls_behave_as_before(domain):
    """exp-h17-001 control rows: state controls -> DENIED, (0, 0); inputs control -> RECONCILED_SUCCESS, 1 effect."""
    from eoo_h17.agents import run_attack
    from eoo_h17.drivers import new_driver
    expected = {"control_state_no_tamper_then_recover": "effects=(0, 0), final=DENIED",
                "control_inputs_no_tamper": "-> RECONCILED_SUCCESS, effects=1"}
    controls = [(n, f) for n, f in _plan(domain) if n.startswith("control")]
    assert len(controls) == (2 if domain == "manufacturing" else 1)
    for n, f in controls:
        r = run_attack(new_driver(domain, "std"), n, "tamper", f)
        assert r["violation"] is False and r["exception"] is None and expected[n] in r["detail"], r
        assert r["world_changed"] is (n == "control_inputs_no_tamper"), r


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_internal_state_flip_to_approved_then_recover_is_denied(domain):
    from eoo_h17 import tamper
    from eoo_h17.drivers import new_driver
    drv = new_driver(domain, "std")
    scn = tamper._intent(drv, "unauthorized")
    rec = drv.engine.tool(scn.principal).propose_action(scn.action, dict(scn.inputs), idempotency_key="t2")
    assert rec["state"] == "DENIED"
    drv.engine._executions[rec["exec"]]["state"] = "APPROVED"
    assert drv.engine.recover() == [{"exec": rec["exec"], "from": "APPROVED", "to": "DENIED"}]
    assert len(drv.engine.effect_log) == 0 and drv.external_count() == 0


def test_domain_internal_state_flip_to_pending_then_approve_is_denied():
    from eoo_h17 import tamper
    from eoo_h17.drivers import new_driver
    drv = new_driver("manufacturing", "std")
    scn = tamper._intent(drv, "unauthorized")
    rec = drv.engine.tool(scn.principal).propose_action(scn.action, dict(scn.inputs), idempotency_key="t1")
    drv.engine._executions[rec["exec"]]["state"] = "PENDING_APPROVAL"
    try:
        drv.engine.approve(rec["exec"], tamper.APPROVER)
    except EngineError:
        pass
    assert len(drv.engine.effect_log) == 0 and drv.external_count() == 0
    assert drv.engine.executions[rec["exec"]]["state"] == "DENIED"


def test_domain_internal_inputs_tamper_then_approve_is_denied():
    from eoo_h17 import tamper
    from eoo_h17.drivers import new_driver
    drv = new_driver("manufacturing", "std")
    scn = tamper._intent(drv, "approval")
    rec = drv.engine.tool(scn.principal).propose_action(scn.action, dict(scn.inputs), idempotency_key="t1")
    assert rec["state"] == "PENDING_APPROVAL"
    drv.engine._executions[rec["exec"]]["inputs"]["quantity"] = -5
    out = drv.engine.approve(rec["exec"], tamper.APPROVER)
    assert out["state"] == "DENIED" and out["gates"][-1]["gate"] == "gate_pass", out["gates"][-1]
    assert len(drv.engine.effect_log) == 0 and drv.external_count() == 0
