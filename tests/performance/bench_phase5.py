#!/usr/bin/env python3
"""Phase 5 item 9 (docs/experiment/briefs/phase5.md) / `make bench-phase5`.

Measures gate evaluation latency PER STAGE (authorization, policy, SHACL/
RDF4J persistence, Postgres index persistence — docs/experiment/spec/
08_test_strategy.md "Performance methodology": "measure separately ... do
not hide slow stages in one average") plus the full end-to-end proposal
path via the real decision_service HTTP API. SLOs come from the LOCKED
experiments/exp-000/manifest.yaml (`gate_evaluation_p95_ms`,
`decision_proposal_p95_ms`) — never redefined here, per common.md's honesty
rule. Writes experiments/exp-000/results/bench-phase5.json.

Run directly: `.venv/bin/python tests/performance/bench_phase5.py` (requires
`make up && make seed`, and a fresh source inventory row this script sets up
itself via WMS's test-mode endpoint).
"""

from __future__ import annotations

import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
import psycopg  # noqa: E402
import yaml  # noqa: E402

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.decision_service import authz, manifest as manifest_mod, policy, rdf_writer, store  # noqa: E402
from services.decision_service.action_types import get_action_type  # noqa: E402
from services.decision_service.evidence import EvidenceResult  # noqa: E402
from services.decision_service.models import APPROVED, DecisionRecord  # noqa: E402
from services.projection_builder import reader  # noqa: E402

RESULTS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "bench-phase5.json"
MANIFEST_PATH = REPO_ROOT / "experiments" / "exp-000" / "manifest.yaml"

N_GATE = 50
N_E2E = 30
SOURCE_WAREHOUSE, DEST_WAREHOUSE = "WH-B", "WH-A"
BENCH_SKU = "SKU-990001"


def percentile(sorted_samples_ms: list[float], p: float) -> float:
    # Duplicated from tests/performance/bench_phase4.py rather than
    # imported: tests/performance/ has no __init__.py (bench_phase4.py
    # itself never needed cross-module imports), and this keeps
    # bench_phase5.py runnable standalone the same way bench_phase4.py is.
    if not sorted_samples_ms:
        return float("nan")
    idx = min(len(sorted_samples_ms) - 1, round(p / 100 * (len(sorted_samples_ms) - 1)))
    return sorted_samples_ms[idx]


def summarize(samples_ms: list[float], warm_or_cold: str) -> dict:
    s = sorted(samples_ms)
    return {
        "condition": warm_or_cold,
        "count": len(s),
        "p50_ms": round(percentile(s, 50), 3),
        "p95_ms": round(percentile(s, 95), 3),
        "p99_ms": round(percentile(s, 99), 3),
        "max_ms": round(s[-1], 3) if s else float("nan"),
    }


def collect_environment() -> dict:
    import os
    import platform
    import subprocess

    env = {"os": platform.platform(), "python": platform.python_version(), "cpu": platform.processor() or platform.machine(), "cpu_count": os.cpu_count()}
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5, check=True)
            env["ram_bytes"] = int(out.stdout.strip())
        else:
            meminfo = Path("/proc/meminfo").read_text()
            env["ram_bytes"] = int(meminfo.splitlines()[0].split()[1]) * 1024
    except Exception as e:  # noqa: BLE001
        env["ram_bytes"] = None
        env["ram_error"] = str(e)
    try:
        out = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=10)
        env["docker_version"] = out.stdout.strip() if out.returncode == 0 else None
    except Exception as e:  # noqa: BLE001
        env["docker_version"] = None
        env["docker_version_error"] = str(e)
    return env


def _time_calls(fn, n: int) -> list[float]:
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def _setup_source_inventory(wms_client: httpx.Client, conn: psycopg.Connection) -> str:
    from tests.integration.decision_helpers import set_inventory_and_wait

    return set_inventory_and_wait(wms_client, conn, BENCH_SKU, SOURCE_WAREHOUSE, on_hand=100000)


def bench_authz(openfga_api_url: str, store_id: str, part: str, n: int) -> list[float]:
    return _time_calls(lambda: authz.check(openfga_api_url, store_id, "can_transfer_inventory", f"warehouse:{SOURCE_WAREHOUSE}", "user", "planner-1"), n)


def bench_policy(opa_base_url: str, action, input_json: dict, n: int) -> list[float]:
    return _time_calls(lambda: policy.evaluate(opa_base_url, action, input_json), n)


def _bench_record(base_record: DecisionRecord) -> DecisionRecord:
    # BOTH decision_id AND evidence_snapshot_id must be unique per call, not
    # just decision_id — found empirically: RDF4J's ShaclSail validates
    # `sh:maxCount` for a given subject ACROSS THE WHOLE REPOSITORY (every
    # named graph), not just the graph in the current transaction (same
    # class of finding as contracts/shapes/v1/fac-core-shape.ttl's Phase 3
    # deviation note). Reusing one fixed `ES-bench-placeholder` subject
    # across many separate decision graphs accumulates multiple
    # oo:snapshotObservedAt/oo:snapshotContentHash triples on that SAME
    # subject once 2+ bench writes exist, and the SECOND run then 409s on
    # `sh:maxCount 1` — this is a benchmark-script bug, not a
    # services/decision_service defect (real propose() calls always mint a
    # fresh uuid-based evidence_snapshot_id per decision).
    unique = uuid.uuid4().hex[:16]
    return DecisionRecord(**{**base_record.__dict__, "decision_id": f"D-bench-{unique}", "evidence_snapshot_id": f"ES-bench-{unique}"})


def bench_rdf_write(rdf4j_client: RDF4JClient, base_record: DecisionRecord, n: int) -> list[float]:
    def _one():
        record = _bench_record(base_record)
        record.conformance_outcome = "CONFORMS"
        committed, detail = rdf_writer.write_decision(rdf4j_client, record)
        assert committed, detail

    return _time_calls(_one, n)


def bench_postgres_persist(conn: psycopg.Connection, base_record: DecisionRecord, n: int) -> list[float]:
    def _one():
        record = _bench_record(base_record)
        record.conformance_outcome = "CONFORMS"
        store.insert_decision(conn, record)

    return _time_calls(_one, n)


def bench_end_to_end(decision_client: httpx.Client, wms_client: httpx.Client, conn: psycopg.Connection, part: str, n: int) -> list[float]:
    samples = []
    for _ in range(n):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE current_inventory SET as_of = now() WHERE part = %s AND warehouse = %s", (part, SOURCE_WAREHOUSE)
            )
        t0 = time.perf_counter()
        r = decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "user", "id": "planner-1"},
                "parameters": {"source_warehouse": SOURCE_WAREHOUSE, "destination_warehouse": DEST_WAREHOUSE, "part": part, "quantity": 10},
            },
        )
        samples.append((time.perf_counter() - t0) * 1000.0)
        assert r.status_code == 200, r.text
    return samples


def main() -> int:
    db_env.load_dotenv()
    manifest_yaml = yaml.safe_load(MANIFEST_PATH.read_text())
    gate_slo_ms = manifest_yaml["slo"]["gate_evaluation_p95_ms"]
    e2e_slo_ms = manifest_yaml["slo"]["decision_proposal_p95_ms"]

    contracts_manifest = manifest_mod.build_manifest()
    action = get_action_type("transfer_inventory")

    wms_base = db_env.http_base_urls()["wms"]
    wms_client = httpx.Client(base_url=wms_base, timeout=10.0)
    decision_client = httpx.Client(base_url=db_env.decision_service_url(), timeout=10.0)
    conn = psycopg.connect(db_env.ontology_hot_dsn(), autocommit=True)
    rdf4j_client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    store_id = authz.resolve_store_id(db_env.openfga_api_url())
    if store_id is None:
        print("OpenFGA store not bootstrapped — run 'make up' first", file=sys.stderr)
        return 2

    part = _setup_source_inventory(wms_client, conn)

    authz_samples = bench_authz(db_env.openfga_api_url(), store_id, part, N_GATE)

    src_row = reader.get_current_inventory(conn, part, SOURCE_WAREHOUSE)
    dest_row = reader.get_current_inventory(conn, part, DEST_WAREHOUSE)
    policy_input = {
        "parameters": {"quantity": 10},
        "evidence": {
            "source_available": src_row["available"],
            "safety_stock": 10,
            "freshness_status": "FRESH",
            "source_quality_status": src_row["quality_status"],
            "destination_quality_status": "OK" if dest_row is None else dest_row["quality_status"],
        },
        "config": {"approval_threshold_units": 100},
    }
    policy_samples = bench_policy(db_env.opa_base_url(), action, policy_input, N_GATE)

    base_record = DecisionRecord(
        decision_id="D-bench-placeholder",
        decision_type="transfer_inventory",
        actor_type="user",
        actor_id="planner-1",
        action_type="transfer_inventory",
        action_version=1,
        parameters={"source_warehouse": SOURCE_WAREHOUSE, "destination_warehouse": DEST_WAREHOUSE, "part": part, "quantity": 10},
        context={},
        ontology_version=contracts_manifest["ontology"]["version"],
        shape_set_version=contracts_manifest["shapes"]["version"],
        authorization_model_version=contracts_manifest["openfga"]["version"],
        policy_bundle_version=contracts_manifest["opa"]["version"],
        evidence_snapshot_id="ES-bench-placeholder",
        status=APPROVED,
        created_at=datetime.now(timezone.utc),
    )
    base_record.evidence = EvidenceResult(
        facts_used={"current_source_inventory": {"available": 100000}},
        facts_excluded={},
        source_positions=[],
        projection_row_hashes=[],
        observed_at=datetime.now(timezone.utc),
        missing=[],
    )
    rdf_write_samples = bench_rdf_write(rdf4j_client, base_record, N_GATE)
    postgres_samples = bench_postgres_persist(conn, base_record, N_GATE)
    e2e_samples = bench_end_to_end(decision_client, wms_client, conn, part, N_E2E)

    stages = {
        "authorization_check": summarize(authz_samples, "warm"),
        "policy_evaluation": summarize(policy_samples, "warm"),
        "shacl_rdf4j_persistence": summarize(rdf_write_samples, "warm"),
        "postgres_index_persistence": summarize(postgres_samples, "warm"),
    }
    gate_p95_ms = max(s["p95_ms"] for s in stages.values())
    e2e_summary = summarize(e2e_samples, "warm")

    gate_slo_pass = gate_p95_ms < gate_slo_ms
    e2e_slo_pass = e2e_summary["p95_ms"] < e2e_slo_ms

    result = {
        "phase": 5,
        "slo": {
            "gate_evaluation_p95_ms": {"threshold_ms": gate_slo_ms, "measured_worst_stage_p95_ms": gate_p95_ms, "pass": gate_slo_pass},
            "decision_proposal_p95_ms": {"threshold_ms": e2e_slo_ms, "measured_p95_ms": e2e_summary["p95_ms"], "pass": e2e_slo_pass,
                                          "note": "excludes human approval wait and external write duration, per H6"},
        },
        "stages": stages,
        "end_to_end_proposal": e2e_summary,
        "environment": collect_environment(),
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(__import__("json").dumps(result, indent=2, sort_keys=True) + "\n")
    print(__import__("json").dumps(result, indent=2, sort_keys=True))
    print(f"\nwrote {RESULTS_PATH}")
    print(f"SLO gate_evaluation_p95_ms: threshold={gate_slo_ms}ms measured={gate_p95_ms}ms -> {'PASS' if gate_slo_pass else 'FAIL'}")
    print(f"SLO decision_proposal_p95_ms: threshold={e2e_slo_ms}ms measured={e2e_summary['p95_ms']}ms -> {'PASS' if e2e_slo_pass else 'FAIL'}")

    rdf4j_client.close()
    wms_client.close()
    decision_client.close()
    conn.close()

    return 0 if (gate_slo_pass and e2e_slo_pass) else 1


if __name__ == "__main__":
    raise SystemExit(main())
