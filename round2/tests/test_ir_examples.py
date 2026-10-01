import json
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "ontology" / "ir.schema.json").read_text())


def test_example_ir_packages_validate():
    for path in sorted((ROOT / "ontology" / "examples").glob("*.json")):
        data = json.loads(path.read_text())
        jsonschema.validate(data, SCHEMA)
