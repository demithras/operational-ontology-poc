#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Freezing without the property-based test dependency would allow a protocol
# to be preregistered while its primary adversarial machinery was silently skipped.
try:
    import hypothesis  # noqa: F401
except ImportError as exc:
    raise SystemExit("Hypothesis is required before protocol freeze. Install: pip install -e '.[test]'") from exc
TARGETS = [
    ROOT / "ontology" / "ir.schema.json",
    ROOT / "protocol" / "thresholds.json",
    ROOT / "docs" / "08_evidence_and_fairness.md",
    ROOT / "ontology" / "semantic-equivalence.md",
    ROOT / "ontology" / "direct_dsl_baseline.md",
] + sorted((ROOT / "hypotheses").glob("h*/contract.json"))

h = hashlib.sha256()
files = []
for p in TARGETS:
    rel = p.relative_to(ROOT).as_posix()
    b = p.read_bytes()
    h.update(rel.encode() + b"\0" + b + b"\0")
    files.append({"path": rel, "sha256": hashlib.sha256(b).hexdigest()})

out = {
    "frozen_at": datetime.now(timezone.utc).isoformat(),
    "protocol_sha256": h.hexdigest(),
    "files": files,
    "warning": "Any material post-reveal change requires a new experiment version and refreeze."
}
(ROOT / "protocol" / "FREEZE.json").write_text(json.dumps(out, indent=2) + "\n")
print(out["protocol_sha256"])
