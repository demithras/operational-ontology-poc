#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

try:
    import jsonschema
except ImportError as exc:
    raise SystemExit("jsonschema is required: pip install -e '.[test]'") from exc

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_IDS = [f"H{i}" for i in range(23, 31)]


def load(path: Path):
    return json.loads(path.read_text())


def main() -> int:
    errors: list[str] = []
    schema = load(ROOT / "schemas" / "hypothesis-contract.schema.json")
    ids: list[str] = []

    contracts = sorted((ROOT / "hypotheses").glob("h*/contract.json"))
    for path in contracts:
        data = load(path)
        ids.append(data.get("id"))
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc.message}")

    if ids != EXPECTED_IDS:
        errors.append(f"hypothesis ids {ids!r} != {EXPECTED_IDS!r}")

    thresholds = load(ROOT / "protocol" / "thresholds.json")
    if thresholds.get("status") != "READY_TO_FREEZE_NOT_YET_PREREGISTERED":
        errors.append("unexpected protocol status")
    for hid in EXPECTED_IDS:
        if hid not in thresholds:
            errors.append(f"missing thresholds for {hid}")

    if thresholds.get("H30", {}).get("min_attack_classes", 0) < 5:
        errors.append("H30 must require at least 5 attack classes")
    if thresholds.get("H30", {}).get("min_blind_realistic_tasks", 0) < 40:
        errors.append("H30 must require at least 40 blind realistic tasks")
    if thresholds.get("H29", {}).get("min_safe_progress_ratio_when_dependencies_available", 0) <= 0:
        errors.append("H29 safe-progress threshold must be explicit and positive")

    invariants = load(ROOT / "threat_model" / "security_invariants.json").get("invariants", [])
    if [x.get("id") for x in invariants] != [
        "P1_AUTHORITY_INTEGRITY", "P2_EFFECT_CONTAINMENT", "P3_KNOWLEDGE_SOVEREIGNTY",
        "P4_PROVENANCE_INTEGRITY", "P5_EXTERNAL_TRUTH", "P6_SAFE_CONTINUITY"
    ]:
        errors.append("Paladin invariant set P1-P6 differs from the expected frozen draft set")

    attacks = load(ROOT / "threat_model" / "attack_classes.json").get("classes", [])
    if len(attacks) < 10 or len({x.get('id') for x in attacks}) != len(attacks):
        errors.append("attack catalog must contain at least 10 unique attack classes")

    envelope = load(ROOT / "threat_model" / "survivability_envelope.json")
    if not envelope.get("fault_classes") or not envelope.get("catastrophic_boundary"):
        errors.append("survivability envelope must state both tested faults and catastrophic boundary")

    upstream = load(ROOT / "protocol" / "UPSTREAM_EVIDENCE.json")
    if upstream.get("main_commit") != "8f9ff26edfb1dba4528d3c31fe8126bc063b9a11":
        errors.append("unexpected Round 2 upstream pin")
    if upstream.get("round2_status", {}).get("H22") != "REJECTED":
        errors.append("Round 3 must inherit H22 as REJECTED, not silently reopen it")

    fairness = (ROOT / "baselines" / "FAIRNESS.md").read_text()
    for phrase in ("least-privilege", "provenance", "reconciliation", "strawman"):
        if phrase.lower() not in fairness.lower():
            errors.append(f"baseline fairness contract missing expected concept: {phrase}")

    dual_path = ROOT / "protocol" / "DUAL_TRACK.json"
    if not dual_path.exists():
        errors.append("protocol/DUAL_TRACK.json missing (author decision 2026-10-06)")
    else:
        dual = load(dual_path)
        if set(dual.get("variants", {})) != {"paladin", "conventional"}:
            errors.append("DUAL_TRACK must define exactly the paladin and conventional variants")
        fields = dual.get("per_gate_verdicts", {}).get("verdict_json_fields", [])
        for f in ("paladin_verdict", "conventional_verdict", "comparative"):
            if f not in fields:
                errors.append(f"DUAL_TRACK per-gate verdict missing field {f}")

    # Dependency sanity: current-round dependencies must point backward.
    for path in contracts:
        data = load(path)
        n = int(data["id"][1:])
        for dep in data.get("upstream_dependencies", []):
            dn = int(dep[1:])
            if 23 <= dn <= 30 and dn >= n:
                errors.append(f"{data['id']} has non-backward current-round dependency {dep}")

    if errors:
        print("PACK INVALID")
        for error in errors:
            print("-", error)
        return 1

    print("PACK OK: H23-H30 contracts, thresholds, P1-P6, A1-A10, survivability envelope and upstream pin validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
