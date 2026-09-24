"""Phase 10a item 5: live proof that services/decision_service exports real
OpenTelemetry spans carrying decision_id/actor_id (propose) and
action_execution_id (execute) to the real otel-collector, landing in its
file-exporter output — the source scripts/gen_traces_reference.py reads.

Requires the full stack including otel-collector reachable, AND the host
bind mount (observability/otel/traces/traces.jsonl) readable from this
process — self-skips with a clear reason otherwise, never a silent pass.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest

from tests.integration.decision_helpers import set_inventory_and_wait
from tests.faults.helpers import approve_if_needed

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACES_FILE = REPO_ROOT / "observability" / "otel" / "traces" / "traces.jsonl"


def _iter_spans(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            for resource_span in doc.get("resourceSpans", []):
                for scope_span in resource_span.get("scopeSpans", []):
                    for span in scope_span.get("spans", []):
                        attrs = {
                            a["key"]: a.get("value", {}).get("stringValue")
                            for a in span.get("attributes", [])
                        }
                        yield span.get("name"), span.get("traceId"), attrs


def _find_span_for_decision(path: Path, decision_id: str, name: str, timeout_s: float = 15.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for span_name, trace_id, attrs in _iter_spans(path):
            if span_name == name and attrs.get("decision_id") == decision_id:
                return trace_id, attrs
        time.sleep(0.5)
    return None, None


def test_propose_and_execute_spans_carry_decision_and_action_ids(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn,
):
    if not TRACES_FILE.exists():
        pytest.skip(f"{TRACES_FILE} does not exist — bring up otel-collector (`make up`) first")

    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-975301", "WH-B", on_hand=50)
    r = decision_client.post(
        "/decisions/propose",
        json={
            "action_type": "transfer_inventory",
            "actor": {"type": "user", "id": "planner-1"},
            "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 1},
            "context": {},
        },
    )
    assert r.status_code == 200, r.text
    decision = r.json()
    decision_id = decision["decision_id"]

    trace_id, attrs = _find_span_for_decision(TRACES_FILE, decision_id, "decision_service.propose")
    assert trace_id is not None, (
        f"no exported 'decision_service.propose' span found for {decision_id} within timeout — "
        f"tracing may not be wired to a live collector"
    )
    assert attrs["actor_id"] == "planner-1", attrs
    assert attrs["action_type"] == "transfer_inventory", attrs
    assert attrs["trace_id"] == trace_id, attrs

    if decision["status"] == "APPROVED":
        decision = approve_if_needed(decision_client, decision)
        assert decision["status"] == "APPROVED", decision
        r2 = decision_client.post(f"/decisions/{decision_id}/execute")
        assert r2.status_code == 202, r2.text
        action_execution_id = r2.json()["action_execution_id"]

        exec_trace_id, exec_attrs = _find_span_for_decision(TRACES_FILE, decision_id, "decision_service.execute")
        assert exec_trace_id is not None, f"no exported 'decision_service.execute' span found for {decision_id}"
        assert exec_attrs["action_execution_id"] == action_execution_id, exec_attrs
