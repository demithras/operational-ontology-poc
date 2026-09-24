#!/usr/bin/env python3
"""Phase 8 item 3's replay/evolution metric for the BASELINE variant — the
same "replay the whole decisions table" idea as
scripts/replay_full_sweep.py (ontology), applied to services/baseline's
own decisions table. Read-only.

    .venv/bin/python scripts/baseline_replay_sweep.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from seed import db_env  # noqa: E402
from services.baseline.replay import ReplayIntegrityError, replay_decision  # noqa: E402


def main() -> int:
    db_env.load_dotenv()
    conn = psycopg.connect(db_env.baseline_dsn(), autocommit=True)
    openfga_api_url = db_env.openfga_api_url()
    opa_base_url = db_env.opa_base_url()

    with conn.cursor() as cur:
        cur.execute("SELECT decision_id FROM decisions ORDER BY decision_id")
        all_ids = [row[0] for row in cur.fetchall()]

    print(f"[baseline_replay_sweep] {len(all_ids)} decisions in baseline.decisions — replaying every one")

    counts: Counter[tuple[str, str]] = Counter()
    bad: list[tuple[str, str, list[str]]] = []
    errors: list[tuple[str, str]] = []
    for decision_id in all_ids:
        try:
            result = replay_decision(decision_id, conn, openfga_api_url, opa_base_url)
        except ReplayIntegrityError as exc:
            errors.append((decision_id, str(exc)))
            continue
        authz_mode = result.replay.get("authz_replay_mode", "?")
        counts[(result.status, authz_mode)] += 1
        if result.status in ("FAIL", "PARTIAL_RECORDED_ONLY"):
            bad.append((decision_id, result.status, result.failure_reasons))

    conn.close()

    print("\n[baseline_replay_sweep] status x authz_mode counts:")
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")
    if errors:
        print(f"\n[baseline_replay_sweep] {len(errors)} decisions raised ReplayIntegrityError (F29):")
        for decision_id, detail in errors[:20]:
            print(f"  {decision_id}: {detail}")
    if bad:
        print(f"\n[baseline_replay_sweep] {len(bad)} decisions are FAIL or PARTIAL_RECORDED_ONLY:")
        for decision_id, status, reasons in bad[:50]:
            print(f"  {decision_id}: {status} {reasons}")

    total = len(all_ids)
    pass_like = sum(v for k, v in counts.items() if k[0] in ("PASS", "PASS_FAIL_CLOSED_VERIFIED"))
    summary = {
        "total_decisions": total,
        "pass_like_count": pass_like,
        "pass_like_pct": round(100 * pass_like / total, 2) if total else None,
        "fail_or_partial_count": len(bad),
        "f29_errors": len(errors),
        "counts": {f"{k[0]}|{k[1]}": v for k, v in counts.items()},
    }
    out_path = REPO_ROOT / "experiments" / "exp-000" / "results" / "baseline-replay-sweep.json"
    out_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\n[baseline_replay_sweep] wrote {out_path}")
    print(f"[baseline_replay_sweep] {pass_like}/{total} ({summary['pass_like_pct']}%) PASS-like, {len(bad)} FAIL/PARTIAL, {len(errors)} F29 errors")
    return 0 if not bad and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
