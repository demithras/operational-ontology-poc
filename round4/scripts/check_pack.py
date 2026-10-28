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
EXPECTED_IDS = [f"H{i}" for i in range(31, 38)]
ADV_KEY = re.compile(r"_advantage_over_baseline_pp")
HEADROOM = {
    "absolute_bar_applies_when_baseline_at_most": 0.80,
    "gap_closure_min_fraction": 0.5,
    "ceiling_when_baseline_at_least": 0.95,
    "ceiling_record": "CEILING: no advantage measured (not REJECTED)",
}
FAULT_SAMPLING = {
    "initial_per_class": 20,
    "batch_size": 20,
    "min_baseline_misses_for_verdict": 10,
    "max_per_class": 200,
    "stop_on": "baseline misses only",
    "below_min_at_cap": "CEILING",
}
H37_THRESHOLDS = {
    "min_seeded_faults_per_class": 20,
    "max_over_broad_grants": 0,
    "max_post_expiry_successful_uses": 0,
    "max_self_approved_grants": 0,
    "max_standing_credentials": 0,
    "min_violation_detection_advantage_over_baseline_pp": 20,
    "max_access_latency_ratio_vs_baseline": 1.5,
    "max_operator_minutes_ratio_vs_baseline": 1.5,
    "revocation_bound_seconds": 60,
    "max_sessions_surviving_revocation": 0,
}
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
            if data["id"] != "H36" and 31 <= int(dep[1:]) and int(dep[1:]) >= n:  # H36 aggregates H37
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
    for c in contracts:  # headroom rule: every advantage-over-baseline evaluator cites it
        ev = c["evaluator"]
        if any(ADV_KEY.search(s) for s in ev["support_if"]):
            if not any("thresholds.headroom_rule" in s and ADV_KEY.search(s) for s in ev["support_if"]):
                errors.append(f"{c['id']}: support_if must cite thresholds.headroom_rule beside the advantage bar")
            if not any("ceiling_when_baseline_at_least" in s and "CEILING" in s for s in ev["inconclusive_if"]):
                errors.append(f"{c['id']}: inconclusive_if must record CEILING when baseline >= ceiling_when_baseline_at_least")
    if "H37" in by_id:
        t = json.dumps(by_id["H37"])
        for needle in ("Vault", "dynamic-credential/JIT tooling already does this", "short TTL, not from the gate", "parity", "real permission state", "F15", "pg_stat_activity", "OpenSearch"):
            if needle not in t:
                errors.append(f"H37 must mention '{needle}'")
        if "observer reads the grant record instead of the target system" not in " ".join(by_id["H37"]["evaluator"]["invalid_if"]):
            errors.append("H37 invalid_if must include the grant-record observer item")
        if by_id["H37"]["upstream_dependencies"] != ["H23", "H24", "H28"]:
            errors.append("H37 upstream_dependencies must be H23, H24, H28")
    if "H36" in by_id:
        t = json.dumps(by_id["H36"])
        if "6 classes" not in t or "CEILING" not in t:
            errors.append("H36 must judge 6 classes and handle CEILING")
        for needle in ("frontier", "parity", "REJECTED", "no advantage measured"):
            if needle not in t:
                errors.append(f"H36 must mention '{needle}'")
    return contracts, by_id


def check_model(errors: list[str], contracts: list[dict]) -> None:
    inv = load(ROOT / "model" / "agent_ops_invariants.json")["invariants"]
    inv_ids = [x["id"] for x in inv]
    if inv_ids != ["C1", "C2", "C3"] + [f"K{i}" for i in range(1, 9)]:
        errors.append(f"invariant ids {inv_ids!r} differ from C1-C3, K1-K8")
    for x in inv:
        for k in ("id", "name", "statement", "violated_when"):
            if not x.get(k):
                errors.append(f"invariant {x.get('id')} missing {k}")
    faults = load(ROOT / "model" / "fault_classes.json")["fault_classes"]
    if [f["id"] for f in faults] != [f"F{i}" for i in range(1, 16)]:
        errors.append("fault class ids must be F1-F15 in order")
    f15 = next((f for f in faults if f["id"] == "F15"), None)
    if not f15 or f15.get("invariant_ids") != ["K7"]:
        errors.append("fault F15 must map to exactly K7")
    for f in faults:
        for k in ("id", "name", "description", "invariant_ids", "injection"):
            if not f.get(k):
                errors.append(f"fault {f.get('id')} missing {k}")
        for iid in f.get("invariant_ids", []):
            if iid not in inv_ids:
                errors.append(f"fault {f['id']} references unknown invariant {iid}")
    actions = load(ROOT / "model" / "actions.json")["actions"]
    want = ["merge_pr", "deploy_release", "push_default_branch", "close_work_item", "write_external_tracker",
            "grant_access", "revoke_access"]
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
    if thr.get("headroom_rule") != HEADROOM:
        errors.append("thresholds.headroom_rule missing or not exactly the four author-fixed keys and values")
    if thr.get("fault_sampling") != FAULT_SAMPLING:
        errors.append("thresholds.fault_sampling missing or not exactly the author-fixed values")
    for c in contracts:
        if c["id"] in ("H31", "H32", "H33", "H34", "H37"):
            if "thresholds.fault_sampling" not in json.dumps(c):
                errors.append(f"{c['id']}: contract must reference thresholds.fault_sampling")
    if thr.get("H37") != H37_THRESHOLDS:
        errors.append("thresholds.H37 missing or not exactly the author-fixed values")
    for sec in ("headroom_rule",):
        for k in thr.get(sec, {}):
            if k.endswith("_rule"):
                errors.append(f"threshold {sec}.{k}: _rule keys are removed")
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


def self_test() -> int:
    """Negative controls: each mutation of a copy of the pack must make check_pack fail."""
    import shutil
    import subprocess
    import sys
    import tempfile

    def mutate_thr(fn):
        def run(root: Path) -> None:
            p = root / "protocol" / "thresholds.json"
            d = json.loads(p.read_text())
            fn(d)
            p.write_text(json.dumps(d, indent=2) + "\n")
        return run

    def mutate_contract(h, fn):
        def run(root: Path) -> None:
            p = root / "hypotheses" / h / "contract.json"
            d = json.loads(p.read_text())
            fn(d)
            p.write_text(json.dumps(d, indent=2) + "\n")
        return run

    def _drop_f15(root: Path) -> None:
        p = root / "model" / "fault_classes.json"
        d = json.loads(p.read_text())
        d["fault_classes"] = [f for f in d["fault_classes"] if f["id"] != "F15"]
        p.write_text(json.dumps(d, indent=2) + "\n")

    def _strip_h37(root: Path) -> None:
        p = root / "hypotheses" / "h37" / "contract.json"
        p.write_text(p.read_text().replace("pg_stat_activity", "x"))

    controls = {
        "remove headroom_rule": mutate_thr(lambda d: d.pop("headroom_rule")),
        "change headroom ceiling value": mutate_thr(lambda d: d["headroom_rule"].update(ceiling_when_baseline_at_least=0.9)),
        "null a threshold": mutate_thr(lambda d: d["H31"].update(max_double_claims_undetected=None)),
        "remove fault_sampling": mutate_thr(lambda d: d.pop("fault_sampling")),
        "remove H37 thresholds": mutate_thr(lambda d: d.pop("H37")),
        "drop conventional-stack rival from H31": mutate_contract("h31", lambda d: d.update(rivals=["a rival that is something else", "another different rival"])),
        "H35 support_if stops citing headroom_rule": mutate_contract("h35", lambda d: d["evaluator"].update(support_if=[s.replace("thresholds.headroom_rule", "thresholds.x") for s in d["evaluator"]["support_if"]])),
        "drop F15 fault class": lambda root: _drop_f15(root),
        "H37 contract stops naming pg_stat_activity": lambda root: _strip_h37(root),
        "H37 threshold loses max_sessions_surviving_revocation": mutate_thr(lambda d: d["H37"].pop("max_sessions_surviving_revocation")),
        "H37 invalid_if loses grant-record item": mutate_contract("h37", lambda d: d["evaluator"].update(invalid_if=[s for s in d["evaluator"]["invalid_if"] if "grant record" not in s])),
    }
    failed = 0
    with tempfile.TemporaryDirectory() as tmp:  # positive control: an unmutated copy must pass
        root = Path(tmp) / "round4"
        shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
        rc = subprocess.run([sys.executable, str(root / "scripts" / "check_pack.py")], capture_output=True, text=True).returncode
    print(f"positive control (unmutated copy): {'passes' if rc == 0 else 'FAILS'}")
    failed += rc != 0
    for name, mutate in controls.items():
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "round4"
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".venv", "__pycache__"))
            mutate(root)
            rc = subprocess.run([sys.executable, str(root / "scripts" / "check_pack.py")], capture_output=True, text=True).returncode
        status = "fails as expected" if rc != 0 else "UNEXPECTEDLY PASSES"
        print(f"negative control '{name}': {status}")
        failed += rc == 0
    return 1 if failed else 0


def main() -> int:
    import sys
    if "--self-test" in sys.argv[1:]:
        return self_test()
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
    print("PACK OK: H31-H37 contracts, model C1-C3/K1-K8/F1-F15, headroom_rule, thresholds, upstream pin and text rules validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
