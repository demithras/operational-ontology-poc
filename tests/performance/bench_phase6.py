#!/usr/bin/env python3
"""Phase 6 item 7 (docs/experiment/briefs/phase6.md) / `make bench-phase6`.

Timing PER STAGE for the durable action runtime (spec 08 "Performance
methodology": "external action duration, CDC observation lag,
reconciliation time ... do not hide slow stages in one average"), measured
through the REAL decision_service -> Temporal -> WMS -> CDC path — never a
synthetic/mocked timing. No SLO gate is locked for these in
experiments/exp-000/manifest.yaml (only `cdc_observation_timeout_s: 30`,
which this script's own `observation_timeout_s` measurement is compared
against as a sanity bound, never redefined) — this is measurement
reporting, matching the brief's own "Timing per stage ... into
bench-phase6.json" wording (no explicit pass/fail criterion for these three
stages, unlike Phase 4/5's hot_read/gate_evaluation SLOs).

Run directly: `.venv/bin/python tests/performance/bench_phase6.py` (requires
`make up && make seed`, decision_client/wms_client reachable).
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
import psycopg  # noqa: E402
import yaml  # noqa: E402

from seed import db_env  # noqa: E402
from services.decision_service.execution import action_execution_id_for  # noqa: E402

RESULTS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "bench-phase6.json"
MANIFEST_PATH = REPO_ROOT / "experiments" / "exp-000" / "manifest.yaml"

N = 10
SOURCE_WAREHOUSE, DEST_WAREHOUSE = "WH-B", "WH-A"
BENCH_SKU_PREFIX = "SKU-995"


def percentile(sorted_samples_ms: list[float], p: float) -> float:
    if not sorted_samples_ms:
        return float("nan")
    idx = min(len(sorted_samples_ms) - 1, round(p / 100 * (len(sorted_samples_ms) - 1)))
    return sorted_samples_ms[idx]


def summarize(samples_ms: list[float]) -> dict:
    s = sorted(x for x in samples_ms if x == x)  # drop NaN
    return {
        "count": len(s),
        "p50_ms": round(percentile(s, 50), 1) if s else None,
        "p95_ms": round(percentile(s, 95), 1) if s else None,
        "p99_ms": round(percentile(s, 99), 1) if s else None,
        "max_ms": round(s[-1], 1) if s else None,
    }


def collect_environment() -> dict:
    import os
    import platform

    return {"os": platform.platform(), "python": platform.python_version(), "cpu_count": os.cpu_count()}


def main() -> int:
    db_env.load_dotenv()
    manifest = yaml.safe_load(MANIFEST_PATH.read_text())
    observation_timeout_s = float(manifest["slo"]["cdc_observation_timeout_s"])

    decision_client = httpx.Client(base_url=db_env.decision_service_url(), timeout=60.0)
    wms_client = httpx.Client(base_url=db_env.http_base_urls()["wms"], timeout=10.0)
    conn = psycopg.connect(db_env.ontology_hot_dsn(), connect_timeout=3, autocommit=True)

    external_action_ms: list[float] = []  # execute() call -> command response observed (via execution GET)
    cdc_observation_ms: list[float] = []  # command committed -> outcome recorded (reconciliationState set)
    end_to_end_ms: list[float] = []  # execute() call -> terminal decision status
    proposal_to_approved_ms: list[float] = []

    for i in range(N):
        sku = f"{BENCH_SKU_PREFIX}{i:03d}"
        wms_client.post("/_test/inventory/set", json={"part": sku, "warehouse_id": SOURCE_WAREHOUSE, "on_hand": 500})
        # No wait_until helper dependency here (tests/integration/ isn't
        # importable standalone-safe for a bench script) — poll current_inventory directly.
        canonical = None
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            with conn.cursor() as cur:
                cur.execute("SELECT part FROM current_inventory WHERE warehouse = %s AND on_hand = 500 AND part LIKE 'PX-%%' ORDER BY part DESC LIMIT 1", (SOURCE_WAREHOUSE,))
                row = cur.fetchone()
            if row:
                canonical = row[0]
                break
            time.sleep(0.5)
        if canonical is None:
            print(f"[bench_phase6] WARNING: sample {i} inventory never converged, skipping")
            continue

        t0 = time.monotonic()
        r = decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "user", "id": "planner-1"},
                "parameters": {"source_warehouse": SOURCE_WAREHOUSE, "destination_warehouse": DEST_WAREHOUSE, "part": canonical, "quantity": 15},
                "context": {},
            },
        )
        t1 = time.monotonic()
        proposal_to_approved_ms.append((t1 - t0) * 1000.0)
        if r.status_code != 200 or r.json()["status"] != "APPROVED":
            continue
        decision_id = r.json()["decision_id"]
        action_execution_id = action_execution_id_for(decision_id)

        t_execute_start = time.monotonic()
        er = decision_client.post(f"/decisions/{decision_id}/execute")
        if er.status_code != 202:
            continue

        # Poll for the command receipt to appear (external action duration).
        t_command_done = None
        deadline = time.monotonic() + observation_timeout_s + 20.0
        while time.monotonic() < deadline:
            exec_row = decision_client.get(f"/executions/{action_execution_id}").json()
            if exec_row.get("commandStatus"):
                t_command_done = time.monotonic()
                break
            time.sleep(0.3)
        if t_command_done is None:
            continue
        external_action_ms.append((t_command_done - t_execute_start) * 1000.0)

        # Poll for the terminal decision status (includes CDC observation).
        t_terminal = None
        final_status = None
        while time.monotonic() < deadline:
            d = decision_client.get(f"/decisions/{decision_id}").json()
            if d["status"] in ("OBSERVED_SUCCESS", "DIVERGED", "OUTCOME_UNKNOWN", "EXECUTION_FAILED"):
                t_terminal = time.monotonic()
                final_status = d["status"]
                break
            time.sleep(0.3)
        if t_terminal is None:
            continue
        end_to_end_ms.append((t_terminal - t_execute_start) * 1000.0)
        cdc_observation_ms.append((t_terminal - t_command_done) * 1000.0)
        print(f"[bench_phase6] sample {i}: final_status={final_status} external_action_ms={external_action_ms[-1]:.0f} cdc_observation_ms={cdc_observation_ms[-1]:.0f}")

    result = {
        "phase": 6,
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": collect_environment(),
        "n_requested": N,
        "stages": {
            "proposal_path_ms": summarize(proposal_to_approved_ms),
            "external_action_duration_ms": summarize(external_action_ms),
            "cdc_observation_lag_ms": summarize(cdc_observation_ms),
            "end_to_end_execution_ms": summarize(end_to_end_ms),
        },
        "note": (
            "No SLO gate locked for these three Phase 6 stages in "
            "experiments/exp-000/manifest.yaml (only cdc_observation_timeout_s=30s, "
            "the ceiling services/action_worker's own poll uses) — measurement "
            "reporting only, per docs/experiment/briefs/phase6.md item 7. "
            "CAVEAT (honest, not hidden): external_action_duration_ms and "
            "cdc_observation_lag_ms are measured via GET /executions/{id}'s "
            "commandStatus field, which services/action_worker/activities.py "
            "only ever writes ONCE, in observe_and_finalize (see "
            "services/common/action_rdf.py's 'exactly two writes' design) — "
            "the SAME write that also records the CDC-correlated outcome. "
            "These two observation points therefore do not cleanly isolate "
            "'WMS command round trip' from 'CDC poll wait' the way spec 08 "
            "asks; end_to_end_execution_ms (execute() call to terminal "
            "decision status) is the one cleanly-measured figure here. A "
            "precise per-activity breakdown would need Temporal's own "
            "workflow-history timestamps (ActivityTaskScheduled/Completed "
            "events per activity) rather than RDF-write observation points "
            "— left as a follow-up, not attempted this session."
        ),
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote {RESULTS_PATH}")
    print(json.dumps(result["stages"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
