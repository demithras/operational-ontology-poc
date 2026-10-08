#!/usr/bin/env python3
"""Generate spec/authority/<domain>.v3.json (G3-E1): the v2 form of the base authority fixture plus a `disclosure` document.

Usage: build_v3_authority.py [--check]   (--check regenerates in memory and diffs against disk; exit 0 iff equal)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rule(rid, effect, principal, typ, reveals, keys=None, via=None):
    ex, fields, links, prov = reveals
    return {"id": rid, "effect": effect, "principal": principal,
            "object": {"type": typ, "keys": keys, "via": via},
            "reveals": {"exists": ex, "fields": fields, "links": links, "provenance": prov}}


def via(link, direction, typ):
    return {"link": link, "dir": direction, "type": typ}


def role(r):
    return {"role": r}


MANUFACTURING = {
    "public_types": ["Warehouse", "Part", "ProductionLine"],
    "public_links": [],
    "rules": [
        rule("m-planner-wo", "allow", role("planner"), "WorkOrder",
             (True, "*", ["WorkOrder_warehouse", "WorkOrder_productionLine", "BomRequirement_workOrder"], "actors")),
        rule("m-supervisor-wo", "allow", role("supervisor"), "WorkOrder",
             (True, ["workOrderId", "status", "priority", "plannedStart", "plannedFinish"], ["WorkOrder_warehouse"], "scalars")),
        rule("m-junior-wo", "allow", role("junior_planner"), "WorkOrder",
             (True, ["workOrderId", "status", "priority"], [], "own")),
        rule("m-junior-wo-deny-plan", "deny", role("junior_planner"), "WorkOrder",
             (False, ["plannedStart", "plannedFinish"], [], "none"), keys=["WO-43"]),
        rule("m-senior-po", "allow", role("senior_approver"), "PurchaseOrder",
             (True, "*", ["PurchaseOrder_suppliedBy", "PurchaseOrderLine_purchaseOrder"], "actors")),
        rule("m-senior-supplier-via-po", "allow", role("senior_approver"), "Supplier",
             (True, ["supplierId", "status"], [], "none"), via=via("PurchaseOrder_suppliedBy", "in", "PurchaseOrder")),
        rule("m-planner-bom-via-wo", "allow", role("planner"), "BomRequirement",
             (True, "*", ["BomRequirement_requiresPart"], "own"), via=via("BomRequirement_workOrder", "out", "WorkOrder")),
        rule("m-planner-lot-via-wh", "allow", {"relation": "planner", "on_type": "Warehouse"}, "InventoryLot",
             (True, ["lotId", "qualityStatus"], ["InventoryLot_warehouse"], "scalars"), via=via("InventoryLot_warehouse", "out", "Warehouse")),
        rule("m-pol-via-po", "allow", role("senior_approver"), "PurchaseOrderLine",
             (True, ["quantity"], [], "none"), via=via("PurchaseOrderLine_purchaseOrder", "out", "PurchaseOrder")),
        rule("m-admin-evidence", "allow", role("admin"), "EvidenceSnapshot", (True, "*", [], "actors")),
        rule("m-admin-identity", "allow", role("admin"), "IdentityMapping", (True, "*", ["IdentityMapping_canonicalId"], "actors")),
        rule("m-admin-lot", "allow", role("admin"), "InventoryLot", (True, "*", ["InventoryLot_warehouse"], "actors")),
        rule("m-admin-shipment", "allow", role("admin"), "Shipment", (True, "*", [], "scalars")),
    ],
}

PROJECT = {
    "public_types": ["Hypothesis", "Metric", "Threshold"],
    "public_links": ["GOVERNED_BY"],
    "rules": [
        rule("p-researcher-rival", "allow", role("researcher"), "Rival", (True, "*", [], "own"),
             via=via("HAS_RIVAL", "in", "Hypothesis")),
        rule("p-researcher-prediction", "allow", role("researcher"), "Prediction", (True, "*", [], "own"),
             via=via("PREDICTS", "in", "Hypothesis")),
        rule("p-researcher-experiment", "allow", role("researcher"), "Experiment",
             (True, ["id", "version", "evaluator_ref"], ["MEASURES", "PRODUCES"], "scalars")),
        rule("p-researcher-evidence-via-exp", "allow", role("researcher"), "Evidence",
             (True, ["id", "payload_hash", "experiment_version"], ["SUPPORTS_OR_REFUTES", "CAPTURED_AT"], "scalars"),
             via=via("PRODUCES", "in", "Experiment")),
        rule("p-researcher-verdict", "allow", role("researcher"), "Verdict",
             (True, "*", ["EVALUATES"], "actors")),
        rule("p-viewer-verdict", "allow", {"any": True}, "Verdict", (True, ["id", "value"], [], "none")),
        rule("p-evidence-agent-evidence", "allow", role("evidence-agent"), "Evidence",
             (True, ["id", "payload_hash", "git_commit"], ["CAPTURED_AT"], "own")),
        rule("p-evidence-agent-commit-via", "allow", role("evidence-agent"), "Commit",
             (True, ["sha"], [], "none"), via=via("CAPTURED_AT", "in", "Evidence")),
        rule("p-draft-agent-decision", "allow", role("draft-agent"), "Decision",
             (True, "*", ["CHANGES"], "actors")),
        rule("p-draft-agent-falsifier", "allow", role("draft-agent"), "Falsifier", (True, ["id"], [], "none")),
        rule("p-researcher-deny-freeze", "deny", role("researcher"), "Experiment",
             (False, ["freeze_hash"], [], "none")),
        rule("p-admin-contract", "allow", role("admin"), "ContractVersion", (True, "*", [], "actors")),
        rule("p-admin-commit", "allow", role("admin"), "Commit", (True, "*", [], "scalars")),
        rule("p-admin-component", "allow", role("admin"), "Component", (True, "*", ["EXISTS_FOR", "VALIDATES"], "actors")),
        rule("p-admin-test", "allow", role("admin"), "Test", (True, "*", ["VALIDATES", "DETECTED_BY"], "scalars")),
        rule("p-admin-failure", "allow", role("admin"), "Failure", (True, "*", ["DETECTED_BY"], "scalars")),
        rule("p-admin-decision", "allow", role("admin"), "Decision", (True, "*", ["CHANGES"], "actors")),
    ],
}

DISCLOSURE = {"manufacturing": MANUFACTURING, "project": PROJECT}


def build(domain: str) -> dict:
    base = json.loads((ROOT / "spec" / "authority" / f"{domain}.json").read_text())
    base.update(spec="r3-authority-3", max_delegation_depth=4, capabilities=[], revoked=[], disclosure=DISCLOSURE[domain])
    base["provenance"] = base["provenance"] + "; v3 = v2 form + disclosure document (scripts/build_v3_authority.py, G3-E1)"
    return base


def outputs() -> dict[Path, str]:
    return {ROOT / "spec" / "authority" / f"{d}.v3.json": json.dumps(build(d), indent=1, sort_keys=True) + "\n"
            for d in DISCLOSURE}


def main(argv: list[str]) -> int:
    outs = outputs()
    if "--check" in argv:
        bad = [str(p.relative_to(ROOT)) for p, s in outs.items() if not p.exists() or p.read_text() != s]
        for b in bad:
            print(f"DIFF: {b}", file=sys.stderr)
        print("v3 authority fixtures up to date" if not bad else f"{len(bad)} file(s) differ")
        return 1 if bad else 0
    for p, s in outs.items():
        p.write_text(s)
        print(f"wrote {p.relative_to(ROOT)} ({len(s)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
