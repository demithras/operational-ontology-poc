"""P1f-5 ObservationClient: read-only, own key, faults, observability classes, deployment scope, strict observation forms."""
import sqlite3

import pytest
from r3_shared import extcap
from r3_shared.extadapter import payload_digest
from r3_shared.extobs import (AudRow, EffRow, ObservationClient, ObserverAuthError, ObserverFault, ObserverUnavailable,
                              key_hash, validate_audit_row, validate_effect_row, validate_snapshot)
from r3_shared.extsystems import load_systems
from tests.p1f_util import PAY, TARGET, cap_for, core


def world(deps=("dep1",)):
    c = core()
    c.advance(1)
    for dep in deps:
        assert c.write(cap_for(c, correlation=f"{dep}-r#0", dep=dep), "expedite", TARGET, PAY, "adp")["status"] == "applied"
    c.advance(2)
    for dep in deps:
        c.write(cap_for(c, target="po:OTHER", correlation=f"{dep}-r#1", dep=dep), "expedite", TARGET, PAY, "adp")   # refused
    return c


def client(c, dep="dep1", fault=None, domain="manufacturing"):
    return ObservationClient(str(c.dir), c.observer_key(dep), load_systems(domain), fault)


def test_read_is_read_only_a_write_raises():
    c = world()
    con = client(c)._connect()
    with pytest.raises(sqlite3.OperationalError):
        con.execute("INSERT INTO effects(tick,deployment,system,operation,target,payload_json,payload_digest,cap_chain,correlation,"
                    "adapter_id) VALUES(9,'dep1','ERP','expedite','x','{}','d','c','r#9','adp')")
    with pytest.raises(sqlite3.OperationalError):
        con.execute("DELETE FROM audit")
    con.close()
    ro = sqlite3.connect(f"file:{c.dir}/external.db?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("UPDATE meta SET v='9'")
    ro.close()


def test_snapshot_rows_and_watermark_filter():
    c = world()
    o = client(c)
    s0 = o.read(0)
    assert (s0.effects, s0.audit, s0.complete_through_tick) == ([], [], 0)
    s1 = o.read(1)
    assert [type(r) for r in s1.effects + s1.audit] == [EffRow, AudRow] and len(s1.effects) == 1 and len(s1.audit) == 1
    s2 = o.read(2)
    assert len(s2.effects) == 1 and [a.reason for a in s2.audit] == ["", "target_mismatch"]
    assert s2.audit[1].outcome == "refused" and s2.audit[1].cap_chain != ""
    validate_snapshot(s2.as_dict())
    assert o.transcript[-1] == {"watermark": 2, "complete_through_tick": 2, "effects": [1], "audit": [1, 2]}


def test_bad_or_foreign_key_raises():
    c = world(("dep1", "dep2"))
    for key in ("", "wrong", "0" * 64):
        with pytest.raises(ObserverAuthError):
            ObservationClient(str(c.dir), key, load_systems("manufacturing")).read(5)
    a, b = client(c, "dep1"), client(c, "dep2")
    assert {r.correlation for r in a.read(5).effects} == {"dep1-r#0"}        # each key sees only its own deployment
    assert {r.correlation for r in b.read(5).effects} == {"dep2-r#0"}
    with pytest.raises(ObserverAuthError):                                  # an action cap is not an observation key
        ObservationClient(str(c.dir), c.issue_root("dep1", "ERP"), load_systems("manufacturing")).read(5)
    assert key_hash(c.observer_key("dep1")) == key_hash(a._key)


def test_unavailable_fault_by_read_index_and_always():
    c = world()
    o = client(c, fault=ObserverFault.unavailable(reads={1}))
    assert o.read(2).effects
    with pytest.raises(ObserverUnavailable):
        o.read(2)
    assert o.read(2).effects                                               # read 2 is fine again
    always = client(c, fault=ObserverFault.unavailable())
    for _ in range(3):
        with pytest.raises(ObserverUnavailable):
            always.read(2)
    assert always.transcript == []


def test_lagging_fault_withholds_rows_above_complete_through_tick():
    c = world()
    s = client(c, fault=ObserverFault.lagging(1)).read(2)
    assert s.complete_through_tick == 1 and len(s.effects) == 1 and [a.reason for a in s.audit] == [""]
    s = client(c, fault=ObserverFault.lagging(2)).read(2)
    assert s.complete_through_tick == 0 and s.effects == [] and s.audit == []
    assert client(c, fault=ObserverFault.lagging(50)).read(2).complete_through_tick == -1
    with pytest.raises(ValueError):
        ObserverFault.lagging(-1)
    with pytest.raises(ValueError):
        ObserverFault("explode")


def test_effects_only_hides_audit_and_none_hides_everything():
    c = core()
    c.advance(1)
    pay = {"work_order_id": "WO-1", "new_planned_start": 7}
    mes = cap_for(c, system="MES", operation="reschedule", target="wo:WO-1", payload=pay, correlation="m#0")
    assert c.write(mes, "reschedule", "wo:WO-1", pay, "adp")["status"] == "applied"
    assert c.write(mes, "reschedule", "wo:WO-1", pay, "adp")["reason"] == "uses_exhausted"
    gen = cap_for(c, system="GEN-NULL", operation="record", target="gen:k", payload={"key": "k"}, correlation="g#0")
    assert c.write(gen, "record", "gen:k", {"key": "k"}, "adp")["status"] == "applied"
    erp = cap_for(c, correlation="e#0")
    c.write(erp, "expedite", TARGET, PAY, "adp")
    s = client(c).read(1)
    by = {r.system for r in s.effects}
    assert by == {"MES", "ERP"}                                              # GEN-NULL (none) omitted
    assert {a.system for a in s.audit} == {"ERP"}                            # MES audit invisible (effects_only); refused attempt too
    assert not [a for a in s.audit if a.reason == "uses_exhausted"]


def test_project_domain_observability_follows_its_own_systems_doc():
    c = core("project")
    c.advance(1)
    pay = {"result_id": "R1"}
    cap = cap_for(c, system="REGISTRY", operation="publish", target="registry:R1", payload=pay, correlation="p#0")
    assert c.write(cap, "publish", "registry:R1", pay, "adp")["status"] == "applied"
    s = client(c, domain="project").read(1)
    assert len(s.effects) == 1 and len(s.audit) == 1


def test_observation_forms_are_strict_known_negatives():
    c = world()
    good = client(c).read(2).as_dict()
    validate_snapshot(good)
    for mut in (lambda d: d.pop("audit"), lambda d: d.update(extra=1), lambda d: d.update(watermark=True),
                lambda d: d["effects"][0].update(tick=-1), lambda d: d["effects"][0].pop("correlation"),
                lambda d: d["audit"][0].update(outcome="maybe"), lambda d: d["audit"][1].update(reason="mystery"),
                lambda d: d["effects"][0].update(payload_digest="xyz"), lambda d: d["effects"][0].update(seq=0)):
        import copy
        bad = copy.deepcopy(good)
        mut(bad)
        with pytest.raises(ValueError):
            validate_snapshot(bad)
    validate_effect_row(good["effects"][0])
    validate_audit_row(good["audit"][1])
    with pytest.raises(ValueError):
        validate_effect_row({**good["effects"][0], "reason": ""})
    with pytest.raises(ValueError):
        validate_audit_row(good["effects"][0])


def test_unreadable_ledger_is_unavailable_not_a_crash(tmp_path):
    o = ObservationClient(str(tmp_path), "k", load_systems("manufacturing"))
    with pytest.raises(ObserverUnavailable):
        o.read(1)
    with pytest.raises(ValueError):
        o.read(-1)
