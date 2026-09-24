#!/usr/bin/env python3
"""Phase 10b item 7 (docs/experiment/briefs/phase10b.md — "FAIR EVOLUTION
COMPARISON"): the baseline-variant twin of seed/generators/historical_corpus.py.

The Phase 8 A/B review found a real fairness gap: `services/baseline` was
built AFTER V1->V2 already happened, so it never accumulated its own
V1-era history — replay-across-evolution (H7/H11's central ontology claim)
was never actually compared between the two variants. This script closes
that gap by generating a REAL V1 (and, after `make deploy-v2`, V2) corpus
through `services/baseline`'s own live HTTP API — never a shortcut/direct
write (that is
seed/generators/bulk_historical_decisions_baseline.py's separate job).

Identical job-mix/outcome-distribution logic to historical_corpus.py
(denied/failed/diverged/unknown coverage), same corpus_helpers.py
functions (they are already base_url-agnostic — the caller supplies which
httpx.Client to drive), a DISJOINT synthetic SKU range so the two variants'
corpora never collide (`SKU-974xxx` v1 / `SKU-975xxx` v2, vs the ontology
generator's `SKU-972xxx`/`SKU-973xxx`).

Usage:
    .venv/bin/python seed/generators/baseline_historical_corpus.py --version v1 --n 110
    # ... make deploy-v2 ...
    .venv/bin/python seed/generators/baseline_historical_corpus.py --version v2 --n 110

Writes/updates experiments/exp-000/results/historical-corpus-baseline.json
(same shape as historical-corpus.json, kept in a SEPARATE file so neither
variant's corpus record is ever silently overwritten by the other's run).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
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

RESULTS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "historical-corpus-baseline.json"

WAREHOUSE_A, WAREHOUSE_B = "WH-A", "WH-B"

# Same shape as seed/generators/historical_corpus.py's own expectation —
# the baseline reads the IDENTICAL contracts/manifests/deployed_version.json
# for authorization/policies/identity (services/baseline/manifest.py's own
# docstring: "both variants version-pin from the exact same live file"), so
# the SAME per-CLI-version expectation applies verbatim.
EXPECTED_LIVE_DEPLOYED_VERSION = {
    "v1": {"policies": "v1", "authorization": "v1", "identity": "v1"},
    "v2": {"policies": "v2", "authorization": "v1", "identity": "v1"},
}


@dataclass
class JobResult:
    decision_id: str | None
    job_kind: str
    final_status: str | None
    error: str | None = None


def _job_plan(version: str, n_executed: int, n_denied: int) -> list[dict]:
    jobs: list[dict] = []
    n_diverged = max(1, round(n_executed * 0.08))
    n_unknown = max(1, round(n_executed * 0.06))
    n_failed = max(1, round(n_executed * 0.06))
    n_normal = n_executed - n_diverged - n_unknown - n_failed
    jobs += [{"kind": "normal", "fault": None} for _ in range(n_normal)]
    jobs += [{"kind": "diverged", "fault": "partial_commit"} for _ in range(n_diverged)]
    jobs += [{"kind": "unknown", "fault": "return_200_without_commit"} for _ in range(n_unknown)]
    jobs += [{"kind": "failed", "fault": "return_500_before_commit"} for _ in range(n_failed)]
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
    db_env.load_dotenv()
    wms = httpx.Client(base_url=db_env.http_base_urls()["wms"], timeout=15.0)
    dec = httpx.Client(base_url=db_env.baseline_service_url(), timeout=15.0)
    conn = psycopg.connect(db_env.ontology_hot_dsn())  # current_inventory lives in ontology_hot's projection — same WMS source, read-only here
    kind = job["kind"]
    version, seq = job["version"], job["seq"]
    # Disjoint from ontology's 972000/973000 and every other reserved range
    # in this repo (see decision_helpers.py's own reserved-range registry).
    base = 974000 if version == "v1" else 975000
    sku = f"SKU-{base + seq:06d}"
    decision_id_so_far: str | None = None
    try:
        if kind == "insufficient_evidence":
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
            canonical = set_inventory_and_wait(wms, conn, sku, WAREHOUSE_B, on_hand=30)
            decision = propose(dec, "planner-1", WAREHOUSE_B, WAREHOUSE_A, canonical, 25)
            decision_id_so_far = decision["decision_id"]
            return JobResult(decision["decision_id"], kind, decision["status"])

        on_hand = 300
        quantity = 20 + (seq % 7) * 15
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
                print(f"[baseline/{version}] {i}/{len(jobs)} done ({time.monotonic() - t0:.0f}s elapsed)")

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


def _assert_live_deployed_version_matches(cli_version: str) -> None:
    from services.common.contract_versions import deployed_version

    live = deployed_version()
    expected = EXPECTED_LIVE_DEPLOYED_VERSION[cli_version]
    mismatches = {k: (expected[k], live.get(k)) for k in expected if live.get(k) != expected[k]}
    if mismatches:
        lines = "\n".join(f"  {k}: expected {exp!r}, live deployed_version.json has {actual!r}" for k, (exp, actual) in mismatches.items())
        raise RuntimeError(
            f"--version {cli_version!r} requested, but the LIVE deployed contract "
            f"(contracts/manifests/deployed_version.json) does not match:\n{lines}\n"
            f"Deploy the matching contract first (make deploy-v2), or reset to the v1 baseline, before "
            f"generating this baseline corpus tier."
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, choices=["v1", "v2"])
    parser.add_argument("--n", type=int, default=110)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    _assert_live_deployed_version_matches(args.version)

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
