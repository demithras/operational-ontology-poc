"""H27 oracle (r3_oracle/provenance.py): evidence set, artifact forms, envelope/root, binding comparison."""
import ast
import copy
from pathlib import Path

import pytest

from r3_oracle import provenance as pv
from r3_shared.opsspec import load_ops_spec

ORACLE = Path(__file__).resolve().parents[1] / "src" / "r3_oracle" / "provenance.py"


def snap_of(ops):
    return {"objects": {f"{o['type']}:{o['key']}": {"props": dict(o["props"]), "version": 1} for o in ops["seed"]["objects"]},
            "links": [], "effects": []}


@pytest.fixture(scope="module")
def mfg():
    return load_ops_spec("manufacturing")


@pytest.fixture(scope="module")
def prj():
    return load_ops_spec("project")


ARGS = {"source_warehouse": "WH-A", "destination_warehouse": "WH-B", "part": "PX-17", "quantity": 5, "work_order": "WO-42"}


def test_evidence_set_is_resource_inputs_plus_newest_term_sorted(mfg):
    ev = pv.evidence_items(mfg, "transfer_inventory", ARGS, snap_of(mfg))
    refs = [e["ref"] for e in ev]
    assert refs == sorted(refs)
    assert {"Warehouse:WH-A", "Warehouse:WH-B", "Part:PX-17", "WorkOrder:WO-42", "EvidenceSnapshot:ES-1"} <= set(refs)
    assert all(e["version"] == 1 and "props" in e for e in ev)


def test_absent_input_is_bound_as_absent(mfg):
    ev = pv.evidence_items(mfg, "transfer_inventory", {**ARGS, "part": "NOPE"}, snap_of(mfg))
    assert {"ref": "Part:NOPE", "absent": True} in ev


def test_newest_term_selects_the_latest_snapshot_and_ties_go_to_smallest_ref(mfg):
    s = snap_of(mfg)
    s["objects"]["EvidenceSnapshot:ES-9"] = {"props": {"snapshotObservedAt": 7}, "version": 3}
    s["objects"]["EvidenceSnapshot:ES-8"] = {"props": {"snapshotObservedAt": 7}, "version": 1}
    refs = [e["ref"] for e in pv.evidence_items(mfg, "transfer_inventory", ARGS, s)]
    assert "EvidenceSnapshot:ES-8" in refs and "EvidenceSnapshot:ES-9" not in refs and "EvidenceSnapshot:ES-1" not in refs


def test_operation_without_newest_term_binds_only_inputs(mfg, prj):
    assert pv.newest_terms(pv.op_of(mfg, "expedite_purchase_order")) == []
    ev = pv.evidence_items(prj, "start_run", {"hypothesis": "H-C"}, snap_of(prj))
    assert [e["ref"] for e in ev] == ["Hypothesis:H-C"]


def test_policy_and_contract_forms(mfg):
    pol, con = pv.policy_artifact(mfg, "transfer_inventory"), pv.contract_artifact(mfg, "transfer_inventory")
    import json
    p, c = json.loads(pol), json.loads(con)
    assert set(p) == {"config", "business_rules", "approval"}
    assert "business_rules" not in c and "approval" not in c and c["helpers"] == mfg["helpers"] and c["spec"] == mfg["spec"]
    m2 = copy.deepcopy(mfg)
    m2["operations"][0]["business_rules"][0]["description"] += "."
    assert pv.sha(pv.policy_artifact(m2, "transfer_inventory")) != pv.sha(pol)       # known negative: one byte of policy
    assert pv.sha(pv.contract_artifact(m2, "transfer_inventory")) == pv.sha(con)     # ... does not touch the contract


def test_delegate_and_revoke_bind_null_policy_and_contract(mfg):
    doc = {"spec": "r3-authority-2", "capabilities": [], "revoked": []}
    b = pv.artifact_blobs("delegate", None, None, mfg, None, doc)
    a = pv.expected_artifacts(b)
    assert a["policy"] == a["contract"] == pv.NULL_DIGEST and a["evidence"] == []


def test_authority_doc_v1_is_the_spec_v2_sorts_revoked(mfg):
    spec = {"spec": "r3-authority-1", "grants": []}
    assert pv.authority_doc(spec) is spec
    d = pv.authority_doc(spec, [{"id": "b"}, {"id": "a"}], ["z", "y"])
    assert d["spec"] == "r3-authority-2" and d["revoked"] == ["y", "z"] and [e["id"] for e in d["capabilities"]] == ["b", "a"]


def test_envelope_root_chain_and_shape():
    dec = {"decision_id": "d1"}
    e1 = pv.make_envelope("s", 1, pv.ZERO, dec, {"x": 1})
    e2 = pv.make_envelope("s", 2, pv.root_of(e1), dec, {"x": 1})
    assert pv.is_envelope(e1) and not pv.is_envelope({**e1, "extra": 1}) and not pv.is_envelope({"v": 1})
    assert pv.root_of(e1) != pv.root_of(e2) and e2["prev"] == pv.root_of(e1)
    assert pv.root_of(e1) == pv.root_of(copy.deepcopy(e1))


def test_find_nested_finds_wrapped_envelope_and_set_nested_replaces_it():
    e = pv.make_envelope("s", 1, pv.ZERO, {}, {})
    rec = {"outer": [{"envelope": e}], "beside": "x"}
    (path, node), = list(pv.find_nested(rec, pv.is_envelope))
    assert node == e
    assert pv.set_nested(rec, path, {"replaced": 1})["outer"][0]["envelope"] == {"replaced": 1}


def test_compare_binding_names_each_difference():
    dec = {k: None for k in pv.DECISION_SCALARS} | {"decision_id": "d", "world_seq": 3, "tick": 1}
    exp = {"decision": dec, "artifacts": {"policy": "p"}}
    env = {"decision": {**dec, "reason": "ok", "authority_path": []}, "artifacts": {"policy": "p"}}
    assert pv.compare_binding(exp, env) == []
    assert pv.compare_binding(exp, {**env, "decision": {**env["decision"], "tick": 2}}) == ["decision.tick"]
    assert pv.compare_binding(exp, {**env, "artifacts": {"policy": "q"}}) == ["artifacts"]
    assert "decision.reason missing" in pv.compare_binding(exp, {**env, "decision": dec})


def test_effect_digest_covers_every_column_and_order():
    rows = [{"seq": 1, "tx": 1, "kind": "create", "ref": "A:1", "data": {}}, {"seq": 2, "tx": 1, "kind": "mark", "ref": "commit", "data": {}}]
    assert pv.effect_digest([]) != pv.effect_digest(rows) != pv.effect_digest(rows[::-1])
    changed = [dict(rows[0], tick=5), rows[1]]
    assert pv.effect_digest(changed) != pv.effect_digest(rows)


def test_provenance_oracle_reads_no_clock_no_rng_and_imports_no_variant():
    tree = ast.parse(ORACLE.read_text())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0:
            mods.add(n.module.split(".")[0])
    assert not mods & {"time", "datetime", "random", "paladin", "conventional", "eoo_engine"}
    assert {m for m in mods if m.startswith("r3_")} <= {"r3_shared"}
