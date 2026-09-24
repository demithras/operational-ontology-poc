#!/usr/bin/env python3
"""Phase 10b items 3/8: experiments/exp-NNN/results/latency.json — merges
`make bench`'s existing per-stage measurements (bench-phase4/5/6.json:
hot-projection read, gate evaluation, end-to-end proposal, external-action
duration, CDC-observation lag) with THIS item's own new measurement: H13
forensic query (q1-q9) timing, on the full historical corpus, for BOTH
variants — the piece spec 08's "Performance methodology" / item 8 asks for
that no earlier phase measured. Host load (services/common/host_load.py)
is recorded at start and end, per that module's own contract.

Ontology side: each of contracts/queries/v1/q1..q9*.rq run directly
against RDF4J via services.common.forensic_queries.run_forensic_query — a
REAL SPARQL round trip per question, per sampled decision.

Baseline side: no separate SPARQL-shaped files exist (this variant has no
RDF core) — the honest relational equivalent is timed instead: q1-q5/q9
each re-fetch GET /decisions/{id} (services/baseline/store.get_decision
already nests gate_results/evidence_snapshot in ONE row per Phase 8's W5
finding, so this is deliberately a full round trip per question, matching
the ontology side's one-call-per-question shape rather than reusing a
cached response — apples to apples on CALL COUNT, not on whether reuse
would have been cheaper), q6=GET /executions/{id}, q7=GET /outcomes/{id},
q8 (which later decisions depended on this outcome) = a real SQL query
over baseline.decisions for the same (part, warehouse) pair created after
this decision's created_at.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from seed import db_env  # noqa: E402
from services.common import host_load  # noqa: E402
from services.common.forensic_queries import run_forensic_query  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402

QUERIES_DIR = REPO_ROOT / "contracts" / "queries" / "v1"


def _pctl(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = min(len(s) - 1, int(round(p / 100 * (len(s) - 1))))
    return round(s[k], 3)


def _stats(samples: list[float]) -> dict:
    if not samples:
        return {"count": 0}
    return {
        "count": len(samples),
        "p50_ms": _pctl(samples, 50), "p95_ms": _pctl(samples, 95),
        "p99_ms": _pctl(samples, 99), "max_ms": round(max(samples), 3),
        "mean_ms": round(statistics.mean(samples), 3),
    }


def _sample_ontology_decision_ids(n: int) -> list[str]:
    db_env.load_dotenv()
    with psycopg.connect(db_env.ontology_hot_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT decision_id FROM decisions WHERE status IN "
            "('OBSERVED_SUCCESS','DIVERGED','OUTCOME_UNKNOWN','APPROVED','REQUIRES_APPROVAL') "
            "ORDER BY random() LIMIT %s", (n,),
        )
        return [r["decision_id"] for r in cur.fetchall()]


def _sample_baseline_decision_ids(n: int) -> list[str]:
    db_env.load_dotenv()
    with psycopg.connect(db_env.baseline_dsn(), row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT decision_id FROM decisions WHERE status IN "
            "('OBSERVED_SUCCESS','DIVERGED','OUTCOME_UNKNOWN','APPROVED','REQUIRES_APPROVAL') "
            "ORDER BY random() LIMIT %s", (n,),
        )
        return [r["decision_id"] for r in cur.fetchall()]


def _time_ontology_h13(n: int) -> dict:
    ids = _sample_ontology_decision_ids(n)
    query_files = sorted(p.name for p in QUERIES_DIR.glob("q*.rq"))
    client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    per_query: dict[str, list[float]] = {f: [] for f in query_files}
    for decision_id in ids:
        for f in query_files:
            t0 = time.perf_counter()
            try:
                run_forensic_query(client, f, decision_id)
            except Exception as exc:  # noqa: BLE001 - timing only; a bad sampled id must not kill the run
                print(f"  [ontology H13] {f} on {decision_id} raised {type(exc).__name__}: {exc}", file=sys.stderr)
                continue
            per_query[f].append((time.perf_counter() - t0) * 1000)
    client.close()
    return {"sample_count": len(ids), "queries": {f: _stats(v) for f, v in per_query.items()}}


def _time_baseline_h13(n: int) -> dict:
    ids = _sample_baseline_decision_ids(n)
    dec = httpx.Client(base_url=db_env.baseline_service_url(), timeout=15.0)
    db_env.load_dotenv()
    conn = psycopg.connect(db_env.baseline_dsn(), row_factory=dict_row)
    per_query: dict[str, list[float]] = {
        f"q{i}_baseline_equiv": [] for i in range(1, 10)
    }
    for decision_id in ids:
        row = None
        for i in (1, 2, 3, 4, 5, 9):
            t0 = time.perf_counter()
            r = dec.get(f"/decisions/{decision_id}")
            elapsed = (time.perf_counter() - t0) * 1000
            if r.status_code == 200:
                row = r.json()
                per_query[f"q{i}_baseline_equiv"].append(elapsed)
        t0 = time.perf_counter()
        exec_resp = dec.get(f"/executions/AX-{decision_id}")
        per_query["q6_baseline_equiv"].append((time.perf_counter() - t0) * 1000)
        if exec_resp.status_code == 200:
            outcome_id = exec_resp.json().get("outcome_id")
            if outcome_id:
                t0 = time.perf_counter()
                dec.get(f"/outcomes/{outcome_id}")
                per_query["q7_baseline_equiv"].append((time.perf_counter() - t0) * 1000)
        if row:
            params = row.get("parameters") or {}
            part, wh = params.get("part"), params.get("source_warehouse")
            created_at = row.get("created_at")
            if part and wh and created_at:
                t0 = time.perf_counter()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT decision_id FROM decisions WHERE parameters->>'part'=%s "
                        "AND parameters->>'source_warehouse'=%s AND created_at > %s "
                        "ORDER BY created_at LIMIT 20",
                        (part, wh, created_at),
                    )
                    cur.fetchall()
                per_query["q8_baseline_equiv"].append((time.perf_counter() - t0) * 1000)
    dec.close()
    conn.close()
    return {"sample_count": len(ids), "queries": {f: _stats(v) for f, v in per_query.items()}}


def generate(results_dir: Path, h13_sample_n: int = 30) -> dict:
    results_dir.mkdir(parents=True, exist_ok=True)
    start_load = host_load.sample_host_load()
    bench = {}
    for name in ("bench-phase4.json", "bench-phase5.json", "bench-phase6.json"):
        p = REPO_ROOT / "experiments" / "exp-000" / "results" / name
        if p.exists():
            bench[name.replace(".json", "").replace("-", "_")] = json.loads(p.read_text())

    print("[gen_latency_report] timing H13 forensic queries (q1-q9) on the ontology variant...")
    ontology_h13 = _time_ontology_h13(h13_sample_n)
    print("[gen_latency_report] timing H13 forensic-equivalent reads on the baseline variant...")
    baseline_h13 = _time_baseline_h13(h13_sample_n)

    end_load = host_load.sample_host_load()

    doc = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "host_load": {"start": start_load.to_dict(), "end": end_load.to_dict(), "note": host_load.contention_note(start_load, end_load)},
        "stage_benchmarks": bench,
        "h13_forensic_query_latency": {
            "ontology": ontology_h13,
            "baseline": baseline_h13,
            "note": (
                "Ontology: each of contracts/queries/v1/q1-q9*.rq run as a real SPARQL round trip against "
                "RDF4J. Baseline: no separate query files exist (no RDF core) — the relational equivalent is "
                "a full GET /decisions/{id} round trip PER QUESTION (q1-q5/q9), GET /executions + GET /outcomes "
                "(q6/q7), and one indexed SQL query for 'later decisions' (q8). services/baseline/store.py "
                "already nests gate_results/evidence into ONE row (Phase 8's W5 finding: a single GET could "
                "answer 6 of 9 questions) — this measurement times a per-question ROUND TRIP on both sides for "
                "an apples-to-apples call-count comparison, not the cheaper 'fetch once, answer locally' path "
                "either variant's real application code would actually take."
            ),
        },
    }
    out_path = results_dir / "latency.json"
    out_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(f"[gen_latency_report] wrote {out_path}")
    return doc


def main() -> int:
    results_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "experiments" / "exp-000" / "results"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    generate(results_dir, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
