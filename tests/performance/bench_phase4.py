#!/usr/bin/env python3
"""Phase 4 item 5 (docs/experiment/briefs/phase4.md) / `make bench`.

Measures hot-projection point-read latency (warm: one reused connection;
cold: a fresh connection per sample) against ontology_hot, AND the
counter-test docs/experiment/spec/01_hypotheses.md H6 asks for: "the
equivalent semantic query directly against the RDF core, to quantify why
the projection exists" — the same WO-42 requirement/inventory facts fetched
via SPARQL against the live RDF4J repository instead.

Writes experiments/exp-000/results/bench-phase4.json. Exits 1 ONLY if the
locked SLO (experiments/exp-000/manifest.yaml `slo.hot_read_p95_ms`) fails
— per docs/experiment/briefs/common.md's honesty rule, this threshold is
read from the locked manifest, never redefined here, and is never tuned
after seeing results.

Run directly: `.venv/bin/python tests/performance/bench_phase4.py`
(requires `make up && make seed` and at least one live projection build —
this script triggers one itself if work_order_risk is empty).
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402
import yaml  # noqa: E402

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.projection_builder.builder import build_all  # noqa: E402
from services.projection_builder.reader import get_work_order_risk  # noqa: E402

RESULTS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "bench-phase4.json"
MANIFEST_PATH = REPO_ROOT / "experiments" / "exp-000" / "manifest.yaml"

WARM_SAMPLES = 200
COLD_SAMPLES = 30
SEMANTIC_CORE_SAMPLES = 50
WORK_ORDER_ID = "WO-42"

SCOPED_SPARQL = """
PREFIX fac: <https://example.local/factory/>
SELECT ?req ?partUri ?qty ?available WHERE {{
  GRAPH <https://example.local/oo/graph/observed> {{
    ?req a fac:BomRequirement ; fac:workOrder <https://example.local/factory/instance/WorkOrder/{wo}> .
    ?req fac:requiresPart ?partUri ; fac:quantity ?qty .
    OPTIONAL {{
      ?lot a fac:InventoryLot ; fac:part ?partUri ; fac:warehouse ?whUri ; fac:availableQuantity ?available .
    }}
  }}
}}
"""


def percentile(sorted_samples_ms: list[float], p: float) -> float:
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


def bench_hot_read_warm(dsn: str, work_order_id: str, n: int) -> list[float]:
    samples = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        # discard the first (connection-setup / query-plan warmup) sample
        get_work_order_risk(conn, work_order_id)
        for _ in range(n):
            t0 = time.perf_counter()
            get_work_order_risk(conn, work_order_id)
            samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def bench_hot_read_cold(dsn: str, work_order_id: str, n: int) -> list[float]:
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        with psycopg.connect(dsn, autocommit=True) as conn:
            get_work_order_risk(conn, work_order_id)
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def bench_semantic_core_direct(client: RDF4JClient, work_order_id: str, n: int) -> list[float]:
    sparql = SCOPED_SPARQL.format(wo=work_order_id)
    samples = []
    client.select(sparql)  # warmup (connection reuse, server-side plan)
    for _ in range(n):
        t0 = time.perf_counter()
        client.select(sparql)
        samples.append((time.perf_counter() - t0) * 1000.0)
    return samples


def collect_environment() -> dict:
    env = {
        "os": platform.platform(),
        "python": platform.python_version(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
    }
    try:
        if platform.system() == "Darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5, check=True)
            env["ram_bytes"] = int(out.stdout.strip())
        else:
            meminfo = Path("/proc/meminfo").read_text()
            kb = int(meminfo.splitlines()[0].split()[1])
            env["ram_bytes"] = kb * 1024
    except Exception as e:  # noqa: BLE001 - environment metadata is best-effort, never fatal
        env["ram_bytes"] = None
        env["ram_error"] = str(e)

    try:
        out = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=10)
        env["docker_version"] = out.stdout.strip() if out.returncode == 0 else None
        if out.returncode != 0:
            env["docker_version_error"] = (out.stderr or "").strip() or "non-zero exit"
    except Exception as e:  # noqa: BLE001
        env["docker_version"] = None
        env["docker_version_error"] = str(e)

    # Container resource limits: not explicitly set in docker-compose.yml
    # (no `deploy.resources.limits` / `mem_limit` on any service) — recorded
    # honestly rather than fabricating a number.
    env["container_resource_limits"] = "not explicitly configured (docker-compose.yml has no deploy.resources.limits)"
    return env


def main() -> int:
    db_env.load_dotenv()
    manifest = yaml.safe_load(MANIFEST_PATH.read_text())
    slo_p95_ms = manifest["slo"]["hot_read_p95_ms"]

    dsn = db_env.ontology_hot_dsn()

    with psycopg.connect(dsn, autocommit=True) as conn:
        row = get_work_order_risk(conn, WORK_ORDER_ID)
        if row is None:
            client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
            try:
                build_all(client, conn)
            finally:
                client.close()
            row = get_work_order_risk(conn, WORK_ORDER_ID)
    if row is None:
        print(f"no work_order_risk row for {WORK_ORDER_ID} even after a build — is the stack seeded?", file=sys.stderr)
        return 2

    warm_samples = bench_hot_read_warm(dsn, WORK_ORDER_ID, WARM_SAMPLES)
    cold_samples = bench_hot_read_cold(dsn, WORK_ORDER_ID, COLD_SAMPLES)

    client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    try:
        semantic_core_samples = bench_semantic_core_direct(client, WORK_ORDER_ID, SEMANTIC_CORE_SAMPLES)
    finally:
        client.close()

    warm_summary = summarize(warm_samples, "warm")
    cold_summary = summarize(cold_samples, "cold")
    semantic_core_summary = summarize(semantic_core_samples, "semantic_core_direct_sparql")

    slo_pass = warm_summary["p95_ms"] < slo_p95_ms

    result = {
        "phase": 4,
        "slo": {
            "name": "hot_read_p95_ms",
            "threshold_ms": slo_p95_ms,
            "measured_warm_p95_ms": warm_summary["p95_ms"],
            "pass": slo_pass,
        },
        "hot_read": {
            "target": "work_order_risk point read (Postgres, ontology_hot)",
            "definitions": {
                "warm": "one psycopg connection reused across all samples (first sample discarded as warmup)",
                "cold": "a fresh psycopg connection opened and closed per sample",
            },
            "warm": warm_summary,
            "cold": cold_summary,
        },
        "counter_test": {
            "target": "equivalent requirement+inventory facts via SPARQL directly against RDF4J",
            "query": SCOPED_SPARQL.format(wo=WORK_ORDER_ID),
            "warm": semantic_core_summary,
        },
        "environment": collect_environment(),
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"\nwrote {RESULTS_PATH}")
    print(f"SLO hot_read_p95_ms: threshold={slo_p95_ms}ms measured(warm)={warm_summary['p95_ms']}ms "
          f"-> {'PASS' if slo_pass else 'FAIL'}")

    return 0 if slo_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
