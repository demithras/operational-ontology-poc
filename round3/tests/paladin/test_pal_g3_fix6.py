"""G3 fix6 (G3-E29): approval thresholds and approver relations are read from the booted ops spec, not hard-coded."""
import copy
import json
from types import SimpleNamespace

import paladin_rig
from paladin.opsrules import RuleSet
from r3_shared.opsspec import load_ops_spec

TR = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
EXP = {"po_id": "PO-992", "expedite_fee": 100}


def _spec_with(op_name, rule_id, edit):
    spec = copy.deepcopy(load_ops_spec("manufacturing"))
    rule = next(r for o in spec["operations"] if o["name"] == op_name for r in o["business_rules"] if r["id"] == rule_id)
    edit(rule["when"])
    return spec


def _rig(tmp_path, monkeypatch, spec):
    monkeypatch.setattr(paladin_rig, "load_ops_spec", lambda domain: spec)
    tmp_path.mkdir(parents=True, exist_ok=True)
    return paladin_rig.Rig(tmp_path, "manufacturing")


def _run(rig, op, args, rid):
    return rig.effects_of(lambda: rig.dep.direct(rig.token("planner-1"), op, args, request_id=rid))


def _lit(n, v):  # replace the threshold literal of a `gt` rule
    n["args"][1]["lit"] = v


def test_units_threshold_is_read_from_the_spec(tmp_path, monkeypatch):
    base = _rig(tmp_path / "a", monkeypatch, load_ops_spec("manufacturing"))
    res, eff = _run(base, "transfer_inventory", TR, "t1")
    assert res.status == "OK" and len(eff) == 1                       # 60 <= 80: no approval needed
    low = _rig(tmp_path / "b", monkeypatch, _spec_with("transfer_inventory", "transfer-large-needs-approval", lambda w: _lit(w, 10)))
    res, eff = _run(low, "transfer_inventory", TR, "t1")
    assert (res.status, res.body["reason"], eff) == ("DENIED", "approval_required", [])   # threshold 10 gates the same call


def test_raised_units_threshold_lets_a_large_transfer_through(tmp_path, monkeypatch):
    big = {**TR, "quantity": 400}
    high = _rig(tmp_path, monkeypatch, _spec_with("transfer_inventory", "transfer-large-needs-approval", lambda w: _lit(w, 1000)))
    res, eff = _run(high, "transfer_inventory", big, "t2")
    assert res.status == "OK" and len(eff) == 1                       # 400 would need an approval under the shipped 80


def test_cost_threshold_is_read_from_the_spec(tmp_path, monkeypatch):
    base = _rig(tmp_path / "a", monkeypatch, load_ops_spec("manufacturing"))
    assert _run(base, "expedite_purchase_order", EXP, "e1")[0].status == "OK"
    low = _rig(tmp_path / "b", monkeypatch, _spec_with("expedite_purchase_order", "expedite-large-fee-needs-approval", lambda w: _lit(w, 50)))
    res, eff = _run(low, "expedite_purchase_order", EXP, "e1")
    assert (res.status, res.body["reason"], eff) == ("DENIED", "approval_required", [])


def test_gating_value_edit_in_the_spec_changes_reschedule(tmp_path, monkeypatch):
    args = {"work_order_id": "WO-43", "new_planned_start": 55}
    spec = _spec_with("reschedule_work_order", "reschedule-high-priority-needs-approval",
                      lambda w: w["args"][1].update(lit="NO-SUCH-PRIORITY"))
    res, eff = _run(_rig(tmp_path, monkeypatch, spec), "reschedule_work_order", args, "r1")
    assert res.status == "OK" and len(eff) == 1


def _route_rules(relations):
    spec = load_ops_spec("manufacturing")
    rule = next(r for o in spec["operations"] if o["name"] == "transfer_inventory" for r in o["business_rules"]
                if r["id"] == "transfer-protected-route")
    ors = rule["when"]["args"][1]["args"][0]["args"]
    for node, rel in zip(ors, relations):
        node["relation"] = rel
    return RuleSet(spec, {"protecting_work_orders": lambda ctx, a: ["WO-1"]})


def _ctx(held):
    p = SimpleNamespace(relations={("Warehouse", "WH-C", r) for r in held}, chain=lambda: [p])
    return SimpleNamespace(principal=p, inputs={**TR})


def test_exempting_relations_are_read_from_the_spec():
    shipped = _route_rules(["planner", "supervisor"])
    assert not shipped.matches(_ctx({"planner"}), "transfer_inventory", "transfer-protected-route")
    assert not shipped.matches(_ctx({"supervisor"}), "transfer_inventory", "transfer-protected-route")
    assert shipped.matches(_ctx({"inspector"}), "transfer_inventory", "transfer-protected-route")
    swapped = _route_rules(["inspector", "supervisor"])               # spec now exempts inspector instead of planner
    assert swapped.matches(_ctx({"planner"}), "transfer_inventory", "transfer-protected-route")
    assert not swapped.matches(_ctx({"inspector"}), "transfer_inventory", "transfer-protected-route")


def test_no_authority_literal_remains_in_paladin_sources():
    import re
    from pathlib import Path
    root = Path(paladin_rig.__file__).resolve().parents[2] / "src" / "paladin"
    pat = re.compile(r"planner|supervisor|APPROVAL_THRESHOLD")
    hits = [f"{f}:{i}" for f in root.rglob("*.py") for i, ln in enumerate(f.read_text().splitlines(), 1) if pat.search(ln)]
    assert hits == []
    assert json.loads((root.parent.parent / "spec" / "ops" / "manufacturing.json").read_text())["config"]["approval_threshold_units"] == 80
