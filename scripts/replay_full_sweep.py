#!/usr/bin/env python3
"""Phase 8 step 0's own verification requirement: "replay the whole
decisions table: 0 FAIL, 0 PARTIAL" — unlike scripts/replay_report.py
(a fixed live-corpus + 500-bulk-decision SAMPLE), this replays every single
row in `ontology_hot.decisions`, whatever that table currently holds
(historical corpus + bulk corpus + any test/fault-injection decisions from
this session). Read-only; never mutates anything.

Run standalone:

    .venv/bin/python scripts/replay_full_sweep.py

Prints a status x authz_mode count table, then the specific list of any
FAIL / PARTIAL_RECORDED_ONLY decision_ids (never averaged away — a single
one means step 0's acceptance bar is not met). Exits 0 if
FAIL == PARTIAL_RECORDED_ONLY == 0, exits 1 otherwise — this script IS a
gate when run explicitly, unlike replay_report.py's always-0 report-only
exit.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.decision_service.replay import ReplayIntegrityError, replay_decision  # noqa: E402


def main() -> int:
    db_env.load_dotenv()
    conn = psycopg.connect(db_env.ontology_hot_dsn(), autocommit=True)
    rdf4j_client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    openfga_api_url = db_env.openfga_api_url()
    opa_base_url = db_env.opa_base_url()

    with conn.cursor() as cur:
        cur.execute("SELECT decision_id FROM decisions ORDER BY decision_id")
        all_ids = [row[0] for row in cur.fetchall()]

    print(f"[replay_full_sweep] {len(all_ids)} decisions in ontology_hot.decisions — replaying every one")

    counts: Counter[tuple[str, str]] = Counter()
    bad: list[tuple[str, str, list[str]]] = []
    errors: list[tuple[str, str]] = []
    for i, decision_id in enumerate(all_ids, start=1):
        try:
            result = replay_decision(decision_id, conn, rdf4j_client, openfga_api_url, opa_base_url)
        except ReplayIntegrityError as exc:
            errors.append((decision_id, str(exc)))
            continue
        authz_mode = result.replay.get("authz_replay_mode", "?")
        counts[(result.status, authz_mode)] += 1
        if result.status in ("FAIL", "PARTIAL_RECORDED_ONLY"):
            bad.append((decision_id, result.status, result.failure_reasons))
        if i % 500 == 0:
            print(f"[replay_full_sweep]   ...{i}/{len(all_ids)}")

    rdf4j_client.close()
    conn.close()

    print("\n[replay_full_sweep] status x authz_mode counts:")
    for key in sorted(counts):
        print(f"  {key}: {counts[key]}")

    if errors:
        print(f"\n[replay_full_sweep] {len(errors)} decisions raised ReplayIntegrityError (F29):")
        for decision_id, detail in errors[:20]:
            print(f"  {decision_id}: {detail}")

    if bad:
        print(f"\n[replay_full_sweep] {len(bad)} decisions are FAIL or PARTIAL_RECORDED_ONLY:")
        for decision_id, status, reasons in bad[:50]:
            print(f"  {decision_id}: {status} {reasons}")
        return 1

    if errors:
        return 1

    print(f"\n[replay_full_sweep] OK — 0 FAIL, 0 PARTIAL_RECORDED_ONLY, 0 F29 errors across {len(all_ids)} decisions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
