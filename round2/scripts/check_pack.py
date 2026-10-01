#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

try:
    import jsonschema
except ImportError as exc:
    raise SystemExit("jsonschema is required: install project dependencies") from exc

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    contract_schema = json.loads((ROOT / "schemas" / "hypothesis-contract.schema.json").read_text())
    ir_schema = json.loads((ROOT / "ontology" / "ir.schema.json").read_text())

    ids = []
    for path in sorted((ROOT / "hypotheses").glob("h*/contract.json")):
        data = json.loads(path.read_text())
        ids.append(data.get("id"))
        try:
            jsonschema.validate(data, contract_schema)
        except jsonschema.ValidationError as e:
            errors.append(f"{path}: schema validation: {e.message}")

    expected = [f"H{i}" for i in range(15, 23)]
    if ids != expected:
        errors.append(f"hypothesis ids {ids!r} != {expected!r}")

    thresholds = json.loads((ROOT / "protocol" / "thresholds.json").read_text())
    if thresholds["H22"]["min_real_domains_for_verdict"] < 3:
        errors.append("H22 must require at least 3 real domains")
    if thresholds["status"] != "READY_TO_FREEZE_NOT_YET_PREREGISTERED":
        errors.append("unexpected preregistration status")

    for field in ("object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules"):
        if field not in ir_schema["properties"]:
            errors.append(f"IR missing {field}")

    for path in sorted((ROOT / "ontology" / "examples").glob("*.json")):
        try:
            jsonschema.validate(json.loads(path.read_text()), ir_schema)
        except jsonschema.ValidationError as e:
            errors.append(f"{path}: IR example invalid: {e.message}")

    if errors:
        print("PACK INVALID")
        for e in errors:
            print("-", e)
        return 1
    print("PACK OK: H15-H22 contracts, thresholds, IR schema and examples validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
