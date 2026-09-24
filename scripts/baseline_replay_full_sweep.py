#!/usr/bin/env python3
"""Baseline-variant twin of scripts/replay_full_sweep.py (Phase 10b item 7):
replays EVERY row in `baseline.decisions`, whatever it currently holds
(live V1/V2 corpus + bulk corpus + A/B workload decisions), via
services.baseline.replay.replay_decision — read-only, never mutates
anything.

Run standalone:

    .venv/bin/python scripts/baseline_replay_full_sweep.py

Prints a status x authz_mode count table, then any FAIL / PARTIAL_RECORDED_ONLY
decision_ids. Exits 0 if FAIL == PARTIAL_RECORDED_ONLY == 0, exits 1 otherwise
— same gate convention as scripts/replay_full_sweep.py.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from seed import db_env  # noqa: E402
from services.baseline.replay import DecisionNotFound, ReplayIntegrityError, replay_decision  # noqa: E402

RESULTS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "baseline-replay-full-sweep.json"


def run() -> dict:
    db_env.load_dotenv()
    conn = psycopg.connect(db_env.baseline_dsn(), autocommit=True)
    openfga_api_url = db_env.openfga_api_url()
    opa_base_url = db_env.opa_base_url()

    with conn.cursor() as cur:
        cur.execute("SELECT decision_id FROM decisions ORDER BY decision_id")
        all_ids = [row[0] for row in cur.fetchall()]

    print(f"[baseline_replay_full_sweep] {len(all_ids)} decisions in baseline.decisions — replaying every one")

    t0 = time.monotonic()
    counts: Counter[tuple[str, str]] = Counter()
    bad: list[tuple[str, str, list[str]]] = []
    errors: list[tuple[str, str]] = []
    for i, decision_id in enumerate(all_ids, start=1):
        try:
            result = replay_decision(decision_id, conn, openfga_api_url, opa_base_url)
        except (ReplayIntegrityError, DecisionNotFound) as exc:
            errors.append((decision_id, str(exc)))
            continue
        authz_mode = result.replay.get("authz_replay_mode", "?")
        counts[(result.status, authz_mode)] += 1
        if result.status in ("FAIL", "PARTIAL_RECORDED_ONLY"):
            bad.append((decision_id, result.status, result.failure_reasons))
        if i % 500 == 0:
            print(f"[baseline_replay_full_sweep]   ...{i}/{len(all_ids)}")

    conn.close()

    pass_like = sum(v for (status, _mode), v in counts.items() if status in ("PASS", "PASS_FAIL_CLOSED_VERIFIED"))
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_decisions": len(all_ids),
        "elapsed_s": round(time.monotonic() - t0, 1),
        "status_x_authz_mode": {f"{s}|{m}": c for (s, m), c in counts.items()},
        "pass_like_count": pass_like,
        "pass_like_rate": round(pass_like / len(all_ids), 4) if all_ids else None,
        "fail_or_partial_count": len(bad),
        "fail_or_partial": [{"decision_id": d, "status": s, "reasons": r} for d, s, r in bad[:200]],
        "replay_integrity_errors": [{"decision_id": d, "detail": e} for d, e in errors[:50]],
    }

    print("\n[baseline_replay_full_sweep] status x authz_mode counts:")
    for key, count in sorted(counts.items()):
        print(f"  {key}: {count}")
    if errors:
        print(f"\n[baseline_replay_full_sweep] {len(errors)} decisions raised a replay error")
    if bad:
        print(f"\n[baseline_replay_full_sweep] {len(bad)} decisions are FAIL or PARTIAL_RECORDED_ONLY")

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> int:
    summary = run()
    return 1 if summary["fail_or_partial_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
