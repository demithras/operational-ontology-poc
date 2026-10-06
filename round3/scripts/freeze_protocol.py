#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    import hypothesis  # noqa: F401
except ImportError as exc:
    raise SystemExit("Hypothesis is required before protocol freeze: pip install -e '.[test]'") from exc

TARGETS = [
    ROOT / "protocol" / "thresholds.json",
    ROOT / "protocol" / "UPSTREAM_EVIDENCE.json",
    ROOT / "baselines" / "FAIRNESS.md",
    ROOT / "docs" / "08_evidence_and_fairness.md",
    ROOT / "docs" / "13_measurement_model.md",
    ROOT / "threat_model" / "security_invariants.json",
    ROOT / "threat_model" / "attack_classes.json",
    ROOT / "threat_model" / "survivability_envelope.json",
    ROOT / "protocol" / "DUAL_TRACK.json",
    ROOT / "protocol" / "AUTHOR_DECISIONS_2026-10-06.md",
] + sorted((ROOT / "hypotheses").glob("h*/contract.json"))

h = hashlib.sha256()
files = []
for path in TARGETS:
    rel = path.relative_to(ROOT).as_posix()
    body = path.read_bytes()
    h.update(rel.encode() + b"\0" + body + b"\0")
    files.append({"path": rel, "sha256": hashlib.sha256(body).hexdigest()})

out = {
    "frozen_at": datetime.now(timezone.utc).isoformat(),
    "protocol_sha256": h.hexdigest(),
    "files": files,
    "warning": "Any material post-reveal change requires a new experiment version and refreeze."
}
(ROOT / "protocol" / "FREEZE.json").write_text(json.dumps(out, indent=2) + "\n")
print(out["protocol_sha256"])
