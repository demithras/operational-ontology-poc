"""H18w: the two exp-h18-001 counterexample classes, RED on contract v2 and GREEN on v3 (domains/project/CHANGES_v3.md).

Class 'supersede_self' (7 illegal accepted) and class 'new_version_chain' (61 legal refused) are reproduced step by step
through the real Engine over a real Git repo; the oracle (oracles/h18/world.py) decides what is legal.
"""
import copy
import json
from pathlib import Path

import pytest

from domains._pack import load_ir
from eoo_exp.util import load_oracle
from eoo_h18.fixture import facts_for
from eoo_h18.gen import classify
from eoo_h18.rig import PRINCIPAL

W = load_oracle("h18", "world")
ROOT = Path(__file__).resolve().parents[2]
COMPLETE = {k: True for k in ("rival", "prediction", "falsifier", "evaluator")}


def _case(rig, ops, phase0="RUNNING", subject="H16"):
    return {"subject": subject, "phase0": phase0, "complete": dict(COMPLETE), "evidence": [], "decision": None, "components": [],
            "facts": facts_for(rig.base_ops, subject, rig.commit0), "ops": ops}


def _run(rig, ops, label, phase0="RUNNING"):
    return rig.run_case(_case(rig, ops, phase0), label)


SELF = [{"k": "evaluate"}, {"k": "supersede", "succ": "self"}]
CHAIN = [{"k": "new_version", "exp": "base"}, {"k": "new_version", "exp": "latest"},
         {"k": "new_version", "exp": "latest"}]


def test_supersede_self_is_the_oracle_illegal_class():
    facts = {"threshold_value": 1, "components": {}, "other": "H17", "exp": "e", "threshold": "t", "cv": "c", "commit": ""}
    w = W.World({"subject": "H16", "phase0": "RUNNING", "complete": COMPLETE, "evidence": [], "decision": None, "components": [], "facts": facts, "ops": []})
    assert w.step({"k": "evaluate"})[0] is True
    pre = copy.deepcopy(w)
    legal, _ = w.step({"k": "supersede", "succ": "self"})
    assert legal is False and "supersede_self" in classify(pre, {"k": "supersede", "succ": "self"}, legal)


def test_v2_RED_self_supersession_is_accepted(rig_v2):
    rows = _run(rig_v2, SELF, "v2-self")
    assert rows[1]["oracle_legal"] is False and rows[1]["divergence"] == "illegal_accepted" and rows[1]["accepted"] is True


def test_v3_GREEN_self_supersession_is_denied_by_the_conflict_policy(rig):
    rows = _run(rig, SELF, "v3-self")
    assert [r.get("divergence") for r in rows] == [None, None]
    r = rows[1]
    assert r["oracle_legal"] is False and r["accepted"] is False and r["denied_gate"] == "policy" and r["new_commits"] == 0
    assert r["summary_match"], r.get("summary_diff")


def test_v3_supersede_with_a_distinct_successor_still_accepted(rig):
    rows = _run(rig, [{"k": "evaluate"}, {"k": "supersede", "succ": "other"}], "v3-sup-ok")
    assert [r["accepted"] for r in rows] == [True, True] and all(r.get("divergence") is None and r["summary_match"] for r in rows)


def test_v2_RED_a_version_chain_is_refused(rig_v2):
    rows = _run(rig_v2, CHAIN, "v2-chain")
    legal_refused = [r for r in rows if r.get("divergence") == "legal_rejected"]
    assert legal_refused and legal_refused[0]["op"] == "new_version" and "new_version_chain" in legal_refused[0]["classes"]


def test_v3_GREEN_a_version_chain_is_accepted_and_linked(rig):
    rows = _run(rig, CHAIN, "v3-chain")
    assert all(r.get("divergence") is None and r["accepted"] and r["summary_match"] for r in rows), [(r["op"], r["state"], r.get("divergence")) for r in rows]
    assert any("new_version_chain" in r["classes"] for r in rows)
    assert rows[-1]["summary"]["versions"] == ["1", "2", "3", "4"]
    files = rig.store.files_at(rig.store.head("refs/heads/case-v3-chain"))
    links = [json.loads(b) for p, b in files.items() if p.startswith("ontology/links/") and json.loads(b)["type"] == "NEW_VERSION_OF"]
    got = sorted((l["src"][1], l["dst"][1]) for l in links)
    assert got == [("exp-h16-001@v2", "exp-h16-001"), ("exp-h16-001@v3", "exp-h16-001@v2"), ("exp-h16-001@v4", "exp-h16-001@v3")]


def test_v3_overwriting_a_version_is_still_refused(rig):
    rows = _run(rig, [{"k": "new_version", "exp": "base"}, {"k": "new_version", "exp": "base"}], "v3-over")
    assert rows[1]["oracle_legal"] is False and rows[1]["accepted"] is False and rows[1].get("divergence") is None and "new_version_overwrite" in rows[1]["classes"]


def test_v3_a_new_version_of_a_draft_hypothesis_is_still_refused(rig):
    rows = _run(rig, [{"k": "new_version", "exp": "base"}], "v3-draft", phase0="DRAFT")
    assert rows[0]["oracle_legal"] is False and rows[0]["accepted"] is False and rows[0].get("divergence") is None


def test_v3_is_v2_plus_exactly_the_two_declared_changes():
    v2, v3 = load_ir("project", "v2"), load_ir("project", "v3")
    a, b = copy.deepcopy(v3), copy.deepcopy(v2)
    assert a["version"] == "v3" and b["version"] == "v2"
    a["version"] = b["version"] = "x"
    for ir in (a, b):
        ir["link_types"] = [l for l in ir["link_types"] if l["id"] != "NEW_VERSION_OF"]
        for act in ir["actions"]:
            if act["id"] == "new_experiment_version":
                act["effects"] = [e for e in act["effects"] if e["target"] != "NEW_VERSION_OF"]
            if act["id"] in ("new_experiment_version", "supersede_hypothesis"):
                act["version"] = "x"
            if act["id"] == "supersede_hypothesis":
                act["policy_refs"] = [p for p in act["policy_refs"] if p != "policy:conflicting_change_denied_with_conflict"]
    assert a == b  # nothing else differs
    assert sum(1 for l in v3["link_types"] if l["id"] == "NEW_VERSION_OF") == 1


def test_ir_v2_is_byte_identical_to_its_committed_version():
    import subprocess
    out = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", "HEAD", "--", "domains/project/ir.v2.json", "domains/project/ir.json"], capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == ""


def test_v2_and_v1_stay_selectable_and_v3_is_the_default():
    assert load_ir("project")["version"] == "v3"
    assert load_ir("project", "v2")["version"] == "v2" and load_ir("project", "v1")["version"] == "v1"
    from domains.project.pack import build_pack
    for v in ("v1", "v2", "v3"):
        build_pack(ir_version=v)
