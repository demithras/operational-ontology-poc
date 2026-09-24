#!/usr/bin/env python3
"""Phase 7 historical corpus generator (docs/experiment/spec/07_versioning_and_replay.md
"Required migration experiment"): creates >= 100 V1 decisions and >= 100 V2
decisions THROUGH THE REAL decision service — never a shortcut/direct write
(that is seed/generators/bulk_historical_decisions.py's separate, explicitly
documented job, for the >= 5,000-total query/load corpus). Real executions
for a comfortable majority of them (targeting >= 200 complete action/outcome
chains total), with denied/failed/diverged/unknown outcomes via the SAME
fault-injection endpoints tests/faults/ already proves correct
(services/wms's `_test/faults/arm`).

Usage:
    .venv/bin/python seed/generators/historical_corpus.py --version v1 --n 110
    # ... deploy V2 (make deploy-v2) ...
    .venv/bin/python seed/generators/historical_corpus.py --version v2 --n 110

Each run APPENDS its decision ids to experiments/exp-000/results/
historical-corpus.json under that version's key — run once per contract
version, in between the make deploy-vN steps (see
docs/experiment/implementation-notes.md Phase 7 section for the exact
sequence this experiment used).

Concurrency: a small bounded thread pool (real, independent HTTP round
trips per job — decision_service already handles concurrent requests, see
tests/faults/test_concurrency_race.py) — kept modest (8 workers) so as not
to starve the shared docker-compose stack's CPU budget while this runs
alongside a developer's own `make test` etc.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
import psycopg  # noqa: E402

from seed import db_env  # noqa: E402
from seed.generators.corpus_helpers import (  # noqa: E402
    action_execution_id_for, approve_if_needed, arm_wms_fault,
    propose, set_inventory_and_wait, start_execution, wait_for_terminal,
)

RESULTS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "historical-corpus.json"

WAREHOUSE_A, WAREHOUSE_B = "WH-A", "WH-B"


@dataclass
class JobResult:
    decision_id: str | None
    job_kind: str
    final_status: str | None
    error: str | None = None


def _job_plan(version: str, n_executed: int, n_denied: int) -> list[dict]:
    """Deterministic-shape job mix (not seeded/random — this experiment
    does not need bit-for-bit reproducibility the way seed/generators/generate.py
    does; only volume and outcome-kind coverage matter here)."""
    jobs: list[dict] = []
    # Fault-mode executed jobs (spec: "denied, failed, diverged, and
    # unknown outcomes via fault injection").
    n_diverged = max(1, round(n_executed * 0.08))
    n_unknown = max(1, round(n_executed * 0.06))
    n_failed = max(1, round(n_executed * 0.06))
    n_normal = n_executed - n_diverged - n_unknown - n_failed
    jobs += [{"kind": "normal", "fault": None} for _ in range(n_normal)]
    jobs += [{"kind": "diverged", "fault": "partial_commit"} for _ in range(n_diverged)]
    jobs += [{"kind": "unknown", "fault": "return_200_without_commit"} for _ in range(n_unknown)]
    jobs += [{"kind": "failed", "fault": "return_500_before_commit"} for _ in range(n_failed)]
    # Propose-time denials (no execution — not part of the "chains" count).
    n_policy = max(1, round(n_denied * 0.4))
    n_authz = max(1, round(n_denied * 0.3))
    n_insufficient = n_denied - n_policy - n_authz
    jobs += [{"kind": "denied_policy"} for _ in range(n_policy)]
    jobs += [{"kind": "denied_authz"} for _ in range(n_authz)]
    jobs += [{"kind": "insufficient_evidence"} for _ in range(max(0, n_insufficient))]
    for i, job in enumerate(jobs):
        job["version"] = version
        job["seq"] = i
    return jobs


def _run_job(job: dict) -> JobResult:
    """Each job gets its OWN httpx clients + psycopg connection — thread-
    safety by construction (no shared mutable client), same as running N
    separate processes would give, at far lower overhead."""
    db_env.load_dotenv()
    wms = httpx.Client(base_url=db_env.http_base_urls()["wms"], timeout=15.0)
    dec = httpx.Client(base_url=db_env.decision_service_url(), timeout=15.0)
    conn = psycopg.connect(db_env.ontology_hot_dsn())
    kind = job["kind"]
    version, seq = job["version"], job["seq"]
    # Dedicated, non-overlapping SKU ranges per version so re-running this
    # script for v1 then v2 never collides on the same (part, warehouse).
    base = 972000 if version == "v1" else 973000
    sku = f"SKU-{base + seq:06d}"
    # Phase 7b fix: tracked OUTSIDE the try block so a failure AFTER
    # propose() succeeded (e.g. approve()/start_execution() 403/500 —
    # observed live: a ~4-minute post-`make reset --build` warm-up window
    # where OpenFGA/decision_service were still settling made 28/110
    # approve() calls 403 transiently) never loses the decision_id of a
    # REAL decision that was genuinely created — the except handler below
    # used to always return decision_id=None here, silently dropping that
    # decision out of historical-corpus.json's decision_ids list even
    # though it exists, fully governed, in Postgres/RDF4J. Found and fixed
    # after having to hand-merge a 50-decision top-up run into the corpus
    # file post-hoc — see docs/experiment/implementation-notes.md Phase 7b
    # section.
    decision_id_so_far: str | None = None
    try:
        if kind == "insufficient_evidence":
            # Never set via WMS at all — current_inventory has no row for
            # this (part, warehouse) pair (F02: "missing evidence").
            canonical = f"PX-{base + seq - 100000:04d}"
            decision = propose(dec, "planner-1", WAREHOUSE_B, WAREHOUSE_A, canonical, 10)
            decision_id_so_far = decision["decision_id"]
            return JobResult(decision["decision_id"], kind, decision["status"])

        if kind == "denied_authz":
            canonical = set_inventory_and_wait(wms, conn, sku, WAREHOUSE_B, on_hand=200)
            decision = propose(dec, "outsider-1", WAREHOUSE_B, WAREHOUSE_A, canonical, 10)
            decision_id_so_far = decision["decision_id"]
            return JobResult(decision["decision_id"], kind, decision["status"])

        if kind == "denied_policy":
            # remaining = 30 - 25 = 5, below BOTH v1's default_safety_stock
            # (10) and v2's (15) — uniform across versions.
            canonical = set_inventory_and_wait(wms, conn, sku, WAREHOUSE_B, on_hand=30)
            decision = propose(dec, "planner-1", WAREHOUSE_B, WAREHOUSE_A, canonical, 25)
            decision_id_so_far = decision["decision_id"]
            return JobResult(decision["decision_id"], kind, decision["status"])

        # --- executed chains (normal / diverged / unknown / failed) ---
        on_hand = 300
        # Vary quantity so some land above v2's 80-unit threshold too
        # (REQUIRES_APPROVAL diversity), never enough to breach safety stock.
        quantity = 20 + (seq % 7) * 15  # 20..110
        canonical = set_inventory_and_wait(wms, conn, sku, WAREHOUSE_B, on_hand=on_hand)
        decision = propose(dec, "planner-1", WAREHOUSE_B, WAREHOUSE_A, canonical, quantity)
        decision_id_so_far = decision["decision_id"]
        decision = approve_if_needed(dec, decision)
        if decision["status"] != "APPROVED":
            return JobResult(decision["decision_id"], kind, decision["status"], error="did not reach APPROVED")

        action_execution_id = action_execution_id_for(decision["decision_id"])
        if job.get("fault"):
            arm_wms_fault(wms, job["fault"], action_execution_id)
        start_execution(dec, decision["decision_id"])
        final = wait_for_terminal(dec, decision["decision_id"], timeout_s=60.0)
        return JobResult(decision["decision_id"], kind, final["status"])
    except Exception as exc:  # noqa: BLE001 - one job's failure must not kill the batch
        return JobResult(decision_id_so_far, kind, None, error=f"{type(exc).__name__}: {exc}")
    finally:
        wms.close()
        dec.close()
        conn.close()


def generate(version: str, n: int, denied_fraction: float = 0.10, max_workers: int = 8) -> dict:
    n_denied = max(1, round(n * denied_fraction))
    n_executed = n - n_denied
    jobs = _job_plan(version, n_executed, n_denied)
    results: list[JobResult] = []
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_job, job) for job in jobs]
        for i, fut in enumerate(as_completed(futures), 1):
            results.append(fut.result())
            if i % 10 == 0 or i == len(jobs):
                print(f"[{version}] {i}/{len(jobs)} done ({time.monotonic() - t0:.0f}s elapsed)")

    errors = [r for r in results if r.error]
    chains = [r for r in results if r.decision_id and r.job_kind not in ("denied_policy", "denied_authz", "insufficient_evidence")]
    denied = [r for r in results if r.job_kind in ("denied_policy", "denied_authz", "insufficient_evidence")]
    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.final_status or "ERROR"] = by_status.get(r.final_status or "ERROR", 0) + 1

    return {
        "version": version,
        "requested": n,
        "decision_ids": [r.decision_id for r in results if r.decision_id],
        "complete_chains": len(chains),
        "denied_or_insufficient": len(denied),
        "errors": [{"job_kind": r.job_kind, "error": r.error} for r in errors],
        "status_counts": by_status,
        "elapsed_s": round(time.monotonic() - t0, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, choices=["v1", "v2"])
    parser.add_argument("--n", type=int, default=110)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    db_env.load_dotenv()
    summary = generate(args.version, args.n, max_workers=args.workers)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if RESULTS_PATH.exists():
        existing = json.loads(RESULTS_PATH.read_text())
    existing[args.version] = summary
    existing["_generated_at_last_update"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    RESULTS_PATH.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")

    print(json.dumps({k: v for k, v in summary.items() if k != "decision_ids"}, indent=2, sort_keys=True))
    if summary["errors"]:
        print(f"WARNING: {len(summary['errors'])} job(s) errored — see {RESULTS_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
