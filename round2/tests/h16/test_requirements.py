"""Domain 2 requirement coverage: 100% on the real project IR; known-negatives (removed carrier, wrong endpoints)."""
import copy
import json

import pytest

from eoo_engine.registry import load_model
from eoo_exp.util import ROOT
from eoo_h16.coverage import requirement_coverage
from eoo_h16.requirements import HARD, LINKS, STATES, TYPES, registry

KINDS = ["object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules",
         "observation_types", "constraints"]
IR = json.loads((ROOT / "domains/project/ir.v2.json").read_text())


def cov(ir):
    return requirement_coverage(ir, KINDS, load_model(ir))


def test_all_registered_requirements_are_carried_by_project_resources():
    c = cov(IR)
    assert c["total"] == len(registry()) >= 57 and c["ok"] == c["total"] and c["failed"] == []


def test_registry_lists_every_docs04_item():
    ids = {r["id"] for r in registry()}
    assert {f"type:{t}" for t in TYPES} <= ids and len(TYPES) == 15
    assert {f"link:{n}" for n, _, _ in LINKS} <= ids and len(LINKS) == 14
    assert {f"state:{s}" for s in STATES} <= ids and "state:terminal_verdicts" in ids
    assert len(HARD) == 7 and {f"rule:{k}" for k in HARD} <= ids  # 6 docs/04 rules; rule 2 covers threshold+falsifier+evaluator
    assert sum(i.startswith("git:") for i in ids) == 6


@pytest.mark.parametrize("kind,rid,req", [("object_types", "Falsifier", "type:Falsifier"),
                                          ("link_types", "FALSIFIED_BY", "link:FALSIFIED_BY"),
                                          ("constraints", "running-requires-freeze-hash", "rule:running_requires_freeze_hash"),
                                          ("policies", "stale_write_rejected", "git:no_silent_stale_write"),
                                          ("functions", "derive_verdict", "rule:verdict_machine_derived")])
def test_removing_a_carrier_fails_that_requirement(kind, rid, req):
    ir = copy.deepcopy(IR)
    ir[kind] = [r for r in ir[kind] if r["id"] != rid]
    c = requirement_coverage(ir, KINDS, _model_without_validation(ir))
    assert req in c["failed"] and c["ok"] < c["total"]


def _model_without_validation(ir):
    class M:
        def get(self, kind, rid):
            return next((r for r in ir[kind] if r["id"] == rid), None)
    return M()


def test_wrong_link_endpoints_fail():
    ir = copy.deepcopy(IR)
    for r in ir["link_types"]:
        if r["id"] == "HAS_RIVAL":
            r["to"] = "Prediction"
    assert "link:HAS_RIVAL" in cov(ir)["failed"]


def test_non_git_change_action_breaks_the_git_authority_requirement():
    ir = copy.deepcopy(IR)
    ir["actions"][0]["effects"][0]["operation"] = "external_call"
    assert "git:durable_actions_are_git_changes" in cov(ir)["failed"]


def test_missing_property_fails():
    ir = copy.deepcopy(IR)
    for o in ir["object_types"]:
        if o["id"] == "Evidence":
            o["properties"] = [p for p in o["properties"] if p["name"] != "environment"]
    assert "prop:Evidence.environment" in requirement_coverage(ir, KINDS, _model_without_validation(ir))["failed"]


def test_unwired_policy_is_reported_not_hidden():
    assert cov(IR)["unwired_policy_or_authority_carriers"] == ["policies:conflicting_change_denied_with_conflict"]


def test_carriers_are_non_kernel_free():
    for r in cov(IR)["requirements"]:
        assert all(c["kernel_kind"] for c in r["carriers"] if "kernel_kind" in c)
