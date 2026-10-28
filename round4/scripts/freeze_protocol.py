#!/usr/bin/env python3
"""Single-stage protocol freeze.

Freezes contracts, model, fairness, measurement model, upstream pin and thresholds
(all thresholds are fixed values). Refuses while protocol/OPEN_QUESTIONS.md has an
unchecked item or any threshold is null. Writes protocol/FREEZE.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PACK_TARGETS = [
    ROOT / "protocol" / "thresholds.json",
    ROOT / "protocol" / "UPSTREAM_EVIDENCE.json",
    ROOT / "protocol" / "preregistration.md",
    ROOT / "protocol" / "AUTHOR_DECISIONS_2026-10-28.md",
    ROOT / "protocol" / "OPEN_QUESTIONS.md",
    ROOT / "baselines" / "FAIRNESS.md",
    ROOT / "docs" / "04_measurement_model.md",
    ROOT / "model" / "agent_ops_invariants.json",
    ROOT / "model" / "fault_classes.json",
    ROOT / "model" / "actions.json",
] + sorted((ROOT / "hypotheses").glob("h*/contract.json"))


def digest(targets: list[Path]) -> tuple[str, list[dict]]:
    h = hashlib.sha256()
    files = []
    for path in targets:
        rel = path.relative_to(ROOT).as_posix()
        body = path.read_bytes()
        h.update(rel.encode() + b"\0" + body + b"\0")
        files.append({"path": rel, "sha256": hashlib.sha256(body).hexdigest()})
    return h.hexdigest(), files


def main() -> int:
    text = (ROOT / "protocol" / "OPEN_QUESTIONS.md").read_text()
    open_items = re.findall(r"^- \[ \] (.+)$", text, flags=re.M)
    if open_items:
        print(f"REFUSED: {len(open_items)} open question(s) in protocol/OPEN_QUESTIONS.md")
        return 2
    thr = json.loads((ROOT / "protocol" / "thresholds.json").read_text())
    nulls = [f"{sec}.{k}" for sec, v in thr.items() if isinstance(v, dict)
             for k, val in v.items() if val is None]
    if nulls:
        print(f"REFUSED: {len(nulls)} threshold(s) are null: {', '.join(nulls)}")
        return 2
    sha, files = digest(PACK_TARGETS)
    out = {
        "stage": "protocol",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "protocol_sha256": sha,
        "files": files,
        "warning": "Any material post-reveal change requires a new experiment version and refreeze.",
    }
    (ROOT / "protocol" / "FREEZE.json").write_text(json.dumps(out, indent=2) + "\n")
    print(sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
