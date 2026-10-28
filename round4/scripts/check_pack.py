#!/usr/bin/env python3
"""Validate the Round 4 draft pack (documents and JSON contracts only)."""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import jsonschema
except ImportError as exc:
    raise SystemExit("jsonschema is required: pip install -e '.[test]'") from exc

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
EXPECTED_IDS = [f"H{i}" for i in range(31, 37)]
PIN = "4058fdd1ccbc94b4ae6286eeb5448f195a5b2aa7"
# Built from parts so this file does not contain the strings it forbids elsewhere.
FORBIDDEN = ["/" + "Users/", "@" + "gmail", "@" + "anthropic"]
THR_REF = re.compile(r"thresholds\.(H\d+|common)\.([a-z0-9_]+)")
SELF_REPORT = "self-report"


def load(path: Path):
    return json.loads(path.read_text())


def check_contracts(errors: list[str]) -> tuple[list[dict], dict]:
    schema = load(ROOT / "schemas" / "hypothesis-contract.schema.json")
    contracts = []
    for path in sorted((ROOT / "hypotheses").glob("h*/contract.json")):
        data = load(path)
        contracts.append(data)
        rel = path.relative_to(ROOT)
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"{rel}: {exc.message}")
        if not (path.parent / "README.md").exists():
            errors.append(f"{rel}: README.md missing next to contract")
        text = json.dumps(data)
        if len(data.get("rivals", [])) < 2:
            errors.append(f"{data['id']}: needs at least 2 rivals")
        if not any("conventional stack already does this" in r for r in data.get("rivals", [])):
            errors.append(f"{data['id']}: a rival must be 'the conventional stack already does this'")
        inv = " ".join(data["evaluator"]["invalid_if"]).lower()
        for needle in (SELF_REPORT, "strawman", "manipulation check"):
            if needle not in inv:
                errors.append(f"{data['id']}: invalid_if must mention '{needle}'")
        if not THR_REF.search(text):
            errors.append(f"{data['id']}: evaluator must reference protocol thresholds (thresholds.<H>.<key>)")
        n = int(data["id"][1:])
        for dep in data.get("upstream_dependencies", []):
            if 31 <= int(dep[1:]) and int(dep[1:]) >= n:
                errors.append(f"{data['id']} has non-backward current-round dependency {dep}")
    ids = [c.get("id") for c in contracts]
    if ids != EXPECTED_IDS:
        errors.append(f"hypothesis ids {ids!r} != {EXPECTED_IDS!r}")
    by_id = {c["id"]: c for c in contracts}
    if "H33" in by_id:
        t = json.dumps(by_id["H33"])
        if "H11" not in t or "parity" not in t:
            errors.append("H33 must name the risk of ending in parity like H11")
    if "H34" in by_id and "strongest" not in json.dumps(by_id["H34"]):
        errors.append("H34 must say it is the expected strongest hypothesis")
    if "H36" in by_id:
        t = json.dumps(by_id["H36"])
        for needle in ("frontier", "parity", "REJECTED", "no advantage measured"):
            if needle not in t:
                errors.append(f"H36 must mention '{needle}'")
    return contracts, by_id


def check_model(errors: list[str], contracts: list[dict]) -> None:
    inv = load(ROOT / "model" / "agent_ops_invariants.json")["invariants"]
    inv_ids = [x["id"] for x in inv]
    if inv_ids != ["C1", "C2", "C3", "K1", "K2", "K3", "K4", "K5"]:
        errors.append(f"invariant ids {inv_ids!r} differ from C1-C3, K1-K5")
    for x in inv:
        for k in ("id", "name", "statement", "violated_when"):
            if not x.get(k):
                errors.append(f"invariant {x.get('id')} missing {k}")
    faults = load(ROOT / "model" / "fault_classes.json")["fault_classes"]
    if [f["id"] for f in faults] != [f"F{i}" for i in range(1, 11)]:
        errors.append("fault class ids must be F1-F10 in order")
    for f in faults:
        for k in ("id", "name", "description", "invariant_ids", "injection"):
            if not f.get(k):
                errors.append(f"fault {f.get('id')} missing {k}")
        for iid in f.get("invariant_ids", []):
            if iid not in inv_ids:
                errors.append(f"fault {f['id']} references unknown invariant {iid}")
    actions = load(ROOT / "model" / "actions.json")["actions"]
    want = ["merge_pr", "deploy_release", "push_default_branch", "close_work_item", "write_external_tracker"]
    if [a["id"] for a in actions] != want:
        errors.append(f"action ids differ from {want}")
    for a in actions:
        for k in ("id", "effect", "external_observer", "required_authority", "required_evidence"):
            if not a.get(k):
                errors.append(f"action {a.get('id')} missing {k}")
    blob = json.dumps(contracts)
    for iid in inv_ids:
        if not re.search(rf"\b{iid}\b", blob):
            errors.append(f"invariant {iid} is not covered by any hypothesis contract")
    for f in faults:
        if not re.search(rf"\b{f['id']}\b", blob):
            errors.append(f"fault class {f['id']} is not covered by any hypothesis contract")


def check_thresholds(errors: list[str], contracts: list[dict]) -> None:
    thr = load(ROOT / "protocol" / "thresholds.json")
    if thr.get("status") != "DRAFT_NOT_FROZEN":
        errors.append("thresholds.json status must be DRAFT_NOT_FROZEN")
    if not isinstance(thr.get("comparative_basis"), str) or "not derived from the baseline pilot" not in thr["comparative_basis"]:
        errors.append("thresholds.json needs a comparative_basis string saying thresholds are not derived from the baseline pilot")
    for sec in EXPECTED_IDS + ["common"]:
        if not isinstance(thr.get(sec), dict):
            errors.append(f"thresholds.json missing section {sec}")
    for sec, body in thr.items():
        if not isinstance(body, dict):
            continue
        for key, val in body.items():
            if val is None:
                errors.append(f"threshold {sec}.{key} is null; all thresholds are author-fixed")
            if key.endswith("_rule"):
                errors.append(f"threshold {sec}.{key}: _rule keys are removed (values are fixed)")
    for ref in thr.get("pilot_values", []):
        sec, _, key = ref.partition(".")
        if key not in thr.get(sec, {}):
            errors.append(f"pilot_values entry {ref} does not exist")
    for c in contracts:
        for sec, key in THR_REF.findall(json.dumps(c)):
            if key not in thr.get(sec, {}):
                errors.append(f"{c['id']} references missing threshold {sec}.{key}")
    for c in contracts:  # every threshold key of a hypothesis is referenced in full by its own contract
        sec = c["id"]
        used = {k for s_, k in THR_REF.findall(json.dumps(c)) if s_ == sec}
        for key in thr.get(sec, {}):
            if not key.endswith("_rule") and key not in used:
                errors.append(f"{sec}: threshold {key} is never referenced as thresholds.{sec}.{key}")
    if (ROOT / "protocol" / "FREEZE.json").exists():
        errors.append("protocol/FREEZE.json exists; the author freezes, not the pack builder")


def check_upstream(errors: list[str]) -> None:
    up = load(ROOT / "protocol" / "UPSTREAM_EVIDENCE.json")
    if up.get("main_commit") != PIN:
        errors.append("unexpected upstream pin")
    r1 = up.get("round1_exp003", {}).get("status", {})
    if r1.get("H11") != "REJECTED" or any(r1.get(f"H{i}") != "SUPPORTED" for i in [*range(1, 11), 12, 13, 14]):
        errors.append("round1 exp-003 verdicts must be H1-H10, H12-H14 SUPPORTED and H11 REJECTED")
    if up.get("round2", {}).get("status", {}).get("H22") != "REJECTED":
        errors.append("round2 H22 must be inherited as REJECTED")
    r3 = up.get("round3", {}).get("status", {})
    if r3.get("H30") != "NOT_RUN" or any(r3.get(f"H{i}") != "SUPPORTED" for i in range(23, 30)):
        errors.append("round3 verdicts must be H23-H29 SUPPORTED and H30 NOT_RUN")
    # Cross-check against the repository files when they are present.
    exp = REPO / "experiments" / "exp-003" / "results" / "hypothesis-results.json"
    if exp.exists():
        real = {k: v.get("status") for k, v in load(exp)["hypotheses"].items()}
        for k, v in r1.items():
            if real.get(k) != v:
                errors.append(f"exp-003 {k}: pack says {v}, repo file says {real.get(k)}")
    res3 = REPO / "round3" / "RESULTS.md"
    if res3.exists() and "NOT RUN" not in res3.read_text():
        errors.append("round3/RESULTS.md no longer says NOT RUN for H30")


def check_text(errors: list[str]) -> None:
    readme = (ROOT / "README.md").read_text()
    flat = re.sub(r"\s+", " ", re.sub(r"^> ?", "", readme, flags=re.M))
    q = ("Does the EOO governance pattern (Decision -> Authorization -> Policy -> Approval -> Action -> Observed Outcome, "
         "plus Round 3 Paladin containment) give AI agents working across several IT projects a measurable coordination "
         "and control advantage over a strong conventional setup (beads task tracker + GitHub branch protection + "
         "CODEOWNERS + required CI)?")
    if q not in flat:
        errors.append("README.md must contain the value question verbatim")
    fair = (ROOT / "baselines" / "FAIRNESS.md").read_text().lower()
    for phrase in ("beads", "branch protection", "codeowners", "required status checks", "required pull request reviews",
                   "dismiss-stale-approvals", "merge queue", "deploy environments", "audit log", "reconciliation script",
                   "strawman"):
        if phrase not in fair:
            errors.append(f"FAIRNESS.md missing: {phrase}")
    for p in sorted((ROOT / "docs").glob("*.md")):
        n = len(p.read_text().splitlines())
        if not 20 <= n <= 60:
            errors.append(f"docs/{p.name} has {n} lines (expected 20-60)")
    for need in ["README.md", "AGENTS.md", "REVIEW_CHECKLIST.md", "CHANGELOG.md", "Makefile", "pyproject.toml", ".gitignore",
                 "scripts/check_pack.py", "scripts/freeze_protocol.py", "scripts/build_file_index.py",
                 "protocol/preregistration.md", "protocol/AUTHOR_DECISIONS_2026-10-28.md", "protocol/OPEN_QUESTIONS.md",
                 "baselines/README.md", "docs/00_research_posture.md", "docs/06_definition_of_done.md"]:
        if not (ROOT / need).exists():
            errors.append(f"missing file {need}")
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT).parts
        if not p.is_file() or ".venv" in rel or "__pycache__" in rel:
            continue
        if p.suffix == ".json":
            try:
                load(p)
            except json.JSONDecodeError as exc:
                errors.append(f"{p.relative_to(ROOT)} does not parse: {exc}")
        try:
            body = p.read_text()
        except UnicodeDecodeError:
            continue
        for bad in FORBIDDEN:
            if bad in body:
                errors.append(f"{p.relative_to(ROOT)} contains forbidden string {bad!r}")


def main() -> int:
    errors: list[str] = []
    contracts, _ = check_contracts(errors)
    check_model(errors, contracts)
    check_thresholds(errors, contracts)
    check_upstream(errors)
    check_text(errors)
    if errors:
        print("PACK INVALID")
        for e in errors:
            print("-", e)
        return 1
    print("PACK OK: H31-H36 contracts, model C1-C3/K1-K5/F1-F10, thresholds, upstream pin and text rules validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
