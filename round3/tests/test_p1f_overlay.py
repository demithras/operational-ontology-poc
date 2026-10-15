"""Q2 ruling: the H28-only project overlay (spec/ops/project.h28.json + spec/authority/project.h28.v3.json) is valid, leaves the base
operations byte-identical, and every external effect of EVERY ops spec (both domains + overlay) resolves to a declared system/
operation whose target rule is satisfiable from the effect payload (P1f-3)."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from r3_shared.authspec import validate_strict
from r3_shared.extsystems import load_systems, placeholders, render_target
from r3_shared.opsspec import validate_ops_spec

ROOT = Path(__file__).resolve().parents[1]
J = lambda p: json.loads((ROOT / p).read_text())  # noqa: E731


def test_ops_overlay_is_valid_and_only_adds_two_operations():
    base, ov = J("spec/ops/project.json"), J("spec/ops/project.h28.json")
    validate_ops_spec(ov)
    assert ov["operations"][:len(base["operations"])] == base["operations"]                 # base ops untouched, same order
    assert [o["name"] for o in ov["operations"][len(base["operations"]):]] == ["publish_result", "notify_reviewer"]
    for k in base:
        if k not in ("operations", "provenance"):
            assert ov[k] == base[k], k
    assert ov["overlay"]["base_sha256"] == hashlib.sha256((ROOT / "spec/ops/project.json").read_bytes()).hexdigest()


def test_base_specs_are_untouched_by_the_overlay():
    assert not any(e.get("kind") == "external" for o in J("spec/ops/project.json")["operations"] for e in o["effects"])


def test_auth_overlay_validates_and_adds_only_h28_grants():
    base, ov, ops = J("spec/authority/project.v3.json"), J("spec/authority/project.h28.v3.json"), J("spec/ops/project.h28.json")
    assert validate_strict(ov, ops)["spec"] == "r3-authority-3"
    new = [g for g in ov["grants"] if g not in base["grants"]]
    assert {g["id"] for g in new} == set(ov["overlay"]["adds_grants"]) and all(g["id"].startswith("h28-") and g["origin"] == "neutral-extension" for g in new)
    assert [g for g in base["grants"] if g not in ov["grants"]] == []
    for k in base:
        if k not in ("grants", "provenance"):
            assert ov[k] == base[k], k
    assert ov["overlay"]["base_sha256"] == hashlib.sha256((ROOT / "spec/authority/project.v3.json").read_bytes()).hexdigest()


def test_overlay_approval_rule_exists_and_its_approver_operation_is_granted():
    ops, auth = J("spec/ops/project.h28.json"), J("spec/authority/project.h28.v3.json")
    op = next(o for o in ops["operations"] if o["name"] == "publish_result")
    assert op["approval"]["required_when_rule"] in [r["id"] for r in op["business_rules"]]
    assert any(g["operation"] == op["approval"]["approver_operation"] and g["effect"] == "allow" for g in auth["grants"])


@pytest.mark.parametrize("doc,systems", [("manufacturing", "manufacturing"), ("project.h28", "project")])
def test_every_external_effect_resolves_to_a_declared_system_and_renders_a_target(doc, systems):
    ops, sysd = J(f"spec/ops/{doc}.json"), load_systems(systems)
    seen = []
    for o in ops["operations"]:
        for e in o["effects"]:
            if e.get("kind") != "external":
                continue
            s = sysd["systems"][e["adapter"]]
            decl = s["operations"][e["target"]]                         # ops-spec `target` is the external operation name
            fields = set(e["payload"])
            assert set(placeholders(decl["target_rule"])) <= fields, (o["name"], decl["target_rule"], fields)
            fake = {k: f"v-{k}" for k in fields}
            assert render_target(decl["target_rule"], fake).count("v-") == len(placeholders(decl["target_rule"]))
            seen.append((e["adapter"], e["target"], s["observability"], decl["idempotency"]))
    want = {"manufacturing": {("WMS", "transfer", "full", "at_most_once"), ("ERP", "expedite", "full", "at_most_once"),
                              ("MES", "reschedule", "effects_only", "idempotent_set")},
            "project": {("REGISTRY", "publish", "full", "at_most_once"), ("NOTIFY", "notify", "effects_only", "idempotent_set")}}
    assert set(seen) == want[systems]


def test_every_declared_non_generated_operation_is_used_by_some_ops_effect():
    for doc, systems in (("manufacturing", "manufacturing"), ("project.h28", "project")):
        used = {(e["adapter"], e["target"]) for o in J(f"spec/ops/{doc}.json")["operations"] for e in o["effects"] if e.get("kind") == "external"}
        declared = {(s, op) for s, d in load_systems(systems)["systems"].items() if not d.get("generated") for op in d["operations"]}
        assert declared == used
