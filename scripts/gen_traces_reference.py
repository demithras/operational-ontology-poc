#!/usr/bin/env python3
"""Phase 10a item 5: `experiments/exp-000/results/traces-reference.txt` —
points the Phase 10b `make experiment`/`make report` pipeline at REAL trace
data instead of a promise. Reads the otel-collector's file-exporter output
directly off its host bind mount (observability/otel/traces/traces.jsonl —
see observability/otel/collector-config.yaml), no docker exec needed.

Run directly:

    .venv/bin/python scripts/gen_traces_reference.py

Never fakes success (common.md honesty rule): if the trace file is empty
or unreadable, the written reference explicitly says so and the script
still exits 0 (this is a reporting tool, not a gate — same convention as
scripts/replay_report.py).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TRACES_FILE = REPO_ROOT / "observability" / "otel" / "traces" / "traces.jsonl"
OUT_FILE = REPO_ROOT / "experiments" / "exp-000" / "results" / "traces-reference.txt"


def _iter_lines(path: Path):
    """The file exporter has been observed to leave stale whitespace
    padding around a line after an external truncation of the file (a
    bind-mount / buffered-writer interaction, not a data problem) — strip
    and skip blank lines rather than fail on them."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if line:
                yield line


def _iter_spans(path: Path):
    for line in _iter_lines(path):
        try:
            doc = json.loads(line)
        except json.JSONDecodeError:
            continue
        for resource_span in doc.get("resourceSpans", []):
            service = None
            for attr in resource_span.get("resource", {}).get("attributes", []):
                if attr.get("key") == "service.name":
                    service = attr.get("value", {}).get("stringValue")
            for scope_span in resource_span.get("scopeSpans", []):
                for span in scope_span.get("spans", []):
                    attrs = {
                        a["key"]: a.get("value", {}).get("stringValue")
                        for a in span.get("attributes", [])
                    }
                    yield {
                        "service": service,
                        "name": span.get("name"),
                        "trace_id": span.get("traceId"),
                        "span_id": span.get("spanId"),
                        "decision_id": attrs.get("decision_id"),
                        "action_execution_id": attrs.get("action_execution_id"),
                        "actor_id": attrs.get("actor_id"),
                    }


def main() -> int:
    spans = list(_iter_spans(TRACES_FILE))
    lines = [
        "# traces-reference.txt -- Phase 10a item 5 (OpenTelemetry, F40)",
        f"# source file: {TRACES_FILE.relative_to(REPO_ROOT)}",
        f"# spans found: {len(spans)}",
        "",
    ]
    if not spans:
        lines.append(
            "NO TRACES FOUND. Either the otel-collector hasn't received any spans yet "
            "(propose/approve/execute at least one decision through decision_service "
            "first), or the trace file doesn't exist at the path above. This is not "
            "silently swallowed -- see tests/faults/test_f40_traces_unavailable.py for "
            "the proof that business correctness does not depend on this file existing."
        )
    else:
        lines.append("# service | span name | trace_id | decision_id | action_execution_id | actor_id")
        for s in spans:
            lines.append(
                f"{s['service']} | {s['name']} | {s['trace_id']} | "
                f"{s['decision_id']} | {s['action_execution_id']} | {s['actor_id']}"
            )
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT_FILE.relative_to(REPO_ROOT)} ({len(spans)} spans)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
