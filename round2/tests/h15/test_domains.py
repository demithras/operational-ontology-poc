"""The two frozen real-domain IR inputs: valid, complete, traceable, reproducible."""
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from eoo_ir import validate
from eoo_ir.conformance import interface_conformance_errors

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
DOMAINS = ["manufacturing", "project"]
KIND_LABEL = {"object_types": "ObjectType", "link_types": "LinkType", "interfaces": "Interface", "functions": "Function",
              "actions": "Action", "policies": "Policy", "authority_rules": "AuthorityRule",
              "observation_types": "ObservationType", "constraints": "Constraint"}
PROJECT_TYPES = ["Hypothesis", "Rival", "Prediction", "Falsifier", "Experiment", "Metric", "Threshold", "Evidence", "Verdict",
                 "Component", "ContractVersion", "Commit", "Test", "Decision", "Failure"]
PROJECT_LINKS = ["HAS_RIVAL", "PREDICTS", "FALSIFIED_BY", "TESTED_BY", "MEASURES", "GOVERNED_BY", "PRODUCES", "SUPPORTS_OR_REFUTES",
                 "EVALUATES", "CAPTURED_AT", "EXISTS_FOR", "VALIDATES", "DETECTED_BY", "CHANGES"]


def load(domain):
    return json.loads((ROOT / "domains" / domain / "ir.json").read_text())


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_ir_validates(domain):
    assert validate(load(domain)) == []


@pytest.mark.parametrize("domain", DOMAINS)
def test_counts_and_interface_with_two_implementers(domain, capsys):
    ir = load(domain)
    counts = {k: len(ir[k]) for k in KIND_LABEL}
    print(f"\n{domain}: {counts}")
    assert all(n > 0 for n in counts.values()), counts
    impl = Counter(i for o in ir["object_types"] for i in o["implements"])
    assert any(n >= 2 for n in impl.values()), impl
    assert interface_conformance_errors(ir) == []
    assert {c["severity"] for c in ir["constraints"]} == {"hard", "soft"}
    assert {a["effect"] for a in ir["authority_rules"]} <= {"allow", "deny"}


def test_manufacturing_has_the_three_governed_actions_and_observations():
    ir = load("manufacturing")
    assert [a["id"] for a in ir["actions"]] == ["transfer_inventory", "expedite_purchase_order", "reschedule_work_order"]
    assert all(a["idempotency"] == "required" for a in ir["actions"])
    assert {o["source_binding"] for o in ir["observation_types"]} == {"ERP_CDC", "MES_CDC", "WMS_CDC"}
    assert {f["id"] for f in ir["functions"]} >= {"work_order_risk", "recommend_transfer_for_work_order"}
    assert not ({f["id"] for f in ir["functions"]} & {a["id"] for a in ir["actions"]})


def test_project_has_required_types_links_and_git_change_lifecycle():
    ir = load("project")
    assert [o["id"] for o in ir["object_types"]] == PROJECT_TYPES
    assert set(PROJECT_LINKS) <= {lk["id"] for lk in ir["link_types"]}
    for a in ir["actions"]:
        assert a["effects"] and all(e["operation"] == "git_change" for e in a["effects"]), a["id"]
    assert {"preregister_hypothesis", "start_run", "attach_evidence", "evaluate_hypothesis", "supersede_hypothesis",
            "record_decision"} <= {a["id"] for a in ir["actions"]}
    assert {"compute_freeze_hash", "derive_verdict", "find_orphan_components"} <= {f["id"] for f in ir["functions"]}
    assert {o["id"] for o in ir["observation_types"]} == {"TestRunObserved", "GitCommitObserved"}
    ev = next(a for a in ir["actions"] if a["id"] == "evaluate_hypothesis")
    assert [p["name"] for p in ev["inputs"]] == ["hypothesis"]  # the verdict is derived, never an input


@pytest.mark.parametrize("domain", DOMAINS)
def test_provenance_covers_every_resource_exactly_once(domain):
    ir = load(domain)
    text = (ROOT / "domains" / domain / "provenance.md").read_text()
    rows = re.findall(r"^\| (\w+) \| `([^`]+)` \| (.*?) \|", text, flags=re.M)
    want = Counter((KIND_LABEL[k], r["id"]) for k in KIND_LABEL for r in ir[k])
    got = Counter((k, i) for k, i, _ in rows)
    assert got == want, {"missing": list((want - got).elements())[:5], "extra": list((got - want).elements())[:5]}
    assert all(src.strip() for _, _, src in rows), "every resource needs a source"
    assert "## Source gaps and decisions" in text


@pytest.mark.parametrize("domain", DOMAINS)
def test_provenance_source_paths_exist(domain):
    text = (ROOT / "domains" / domain / "provenance.md").read_text()
    paths = set(re.findall(r"(?<![\w/.-])((?:contracts|reference_model|services|docs|src|scripts|protocol|ontology)/[\w./-]*\w|AGENTS\.md)", text))
    assert paths
    missing = sorted(p for p in paths if not ((REPO / p).exists() or (ROOT / p).exists()))
    assert not missing, missing


def test_builders_reproduce_the_committed_files():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_domain_ir.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_manufacturing_covers_every_class_and_domain_property_declared_in_the_ontology():
    """Source-coverage guard: nothing the v3 ontology declares was silently dropped."""
    ir = load("manufacturing")
    props = {o["id"]: {p["name"] for p in o["properties"]} for o in ir["object_types"]}
    links = {lk["id"] for lk in ir["link_types"]}
    classes, datatype, objprop = set(), [], []
    for f in ("fac-core.ttl", "oo-core.ttl", "oo-observation.ttl"):
        t = (REPO / "contracts/ontology/v3" / f).read_text()
        classes |= set(re.findall(r"^(?:fac|oo):(\w+)\s+a owl:Class", t, flags=re.M))
        for m in re.finditer(r"^(?:fac|oo):(\w+)\s+a owl:(Datatype|Object)Property\s*;([^.]*?)\.\s*$", t, flags=re.M | re.S):
            d = re.search(r"rdfs:domain (?:fac|oo):(\w+)", m.group(3))
            if d:
                (datatype if m.group(2) == "Datatype" else objprop).append((d.group(1), m.group(1)))
    assert classes - set(props) == set(), classes - set(props)
    assert len(datatype) > 40 and len(objprop) > 10  # known-positive: the scan really saw the declarations
    assert [(c, n) for c, n in datatype if n not in props.get(c, ())] == []
    skipped_inverse = {("PurchaseOrder", "hasLine"), ("WorkOrder", "hasRequirement")}  # documentation-only inverses, see provenance
    assert [(c, n) for c, n in objprop if not any(lk.startswith(f"{c}_{n}") for lk in links) and (c, n) not in skipped_inverse] == []
