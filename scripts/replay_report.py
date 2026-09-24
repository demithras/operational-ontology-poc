#!/usr/bin/env python3
"""Phase 7b item D: "make test-replay reports counts by mode and status" —
run standalone (Makefile's `test-replay` target runs this AFTER pytest, see
Makefile) or directly:

    .venv/bin/python scripts/replay_report.py

Replays the FULL live corpus (experiments/exp-000/results/historical-corpus.json,
v1 + v2 — the same population tests/replay/test_replay_corpus.py verifies)
plus a deterministic sample of D-BULK* decisions (same SAMPLE_SIZE/ordering
as tests/replay/test_bulk_replay_sample.py, so the two agree), and prints a
plain-text table: corpus size by origin x generation x replay status x
authz mode — the exact breakdown docs/experiment/briefs/phase7b.md's
Verification section asks for. Never mutates anything; read-only replay
calls only. Exits 0 always (this is a REPORT, not a gate — `make
test-replay`'s pytest run is the actual pass/fail authority); prints a
loud warning line if any group is not 100% PASS/live so the summary is
never silently misleading.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.decision_service.replay import replay_decision  # noqa: E402

CORPUS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "historical-corpus.json"
BULK_SAMPLE_SIZE = 500


def _live_decision_ids() -> list[str]:
    import json

    if not CORPUS_PATH.exists():
        return []
    data = json.loads(CORPUS_PATH.read_text())
    ids = []
    for version in ("v1", "v2"):
        ids.extend(data.get(version, {}).get("decision_ids", []))
    return ids


def _bulk_decision_ids(conn: psycopg.Connection, limit: int = BULK_SAMPLE_SIZE) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT decision_id FROM decisions WHERE decision_id LIKE 'D-BULK%%' ORDER BY decision_id LIMIT %s", (limit,))
        return [row[0] for row in cur.fetchall()]


def main() -> int:
    db_env.load_dotenv()
    conn = psycopg.connect(db_env.ontology_hot_dsn(), autocommit=True)
    rdf4j_client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    openfga_api_url = db_env.openfga_api_url()
    opa_base_url = db_env.opa_base_url()

    live_ids = _live_decision_ids()
    bulk_ids = _bulk_decision_ids(conn)
    if not live_ids and not bulk_ids:
        print("[replay_report] no corpus found (neither historical-corpus.json nor D-BULK* rows) — nothing to report", file=sys.stderr)
        return 0

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT decision_id, action_version_dir, context->>'origin' AS origin FROM decisions WHERE decision_id = ANY(%s)", (live_ids + bulk_ids,))
        meta = {row["decision_id"]: row for row in cur.fetchall()}

    counts: Counter[tuple[str, str, str, str]] = Counter()
    total = 0
    for decision_id in live_ids + bulk_ids:
        row = meta.get(decision_id, {})
        generation = row.get("action_version_dir") or "unknown"
        origin = row.get("origin") or ("bulk-evaluated" if decision_id.startswith("D-BULK") else "live")
        result = replay_decision(decision_id, conn, rdf4j_client, openfga_api_url, opa_base_url)
        authz_mode = result.replay.get("authz_replay_mode", "?")
        counts[(origin, generation, result.status, authz_mode)] += 1
        total += 1

    rdf4j_client.close()
    conn.close()

    header = ["origin", "generation", "replay_status", "authz_mode", "count"]
    rows = [list(key) + [str(counts[key])] for key in sorted(counts)]
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i]) for i in range(5)]

    def _fmt(row) -> str:
        return "  ".join(str(v).ljust(w) for v, w in zip(row, widths))

    print(f"\n[replay_report] {total} decisions replayed ({len(live_ids)} live, {len(bulk_ids)} bulk-evaluated sample)\n")
    print(_fmt(header))
    print(_fmt(["-" * w for w in widths]))
    for row in rows:
        print(_fmt(row))

    non_ideal = {k: v for k, v in counts.items() if k[2] != "PASS" or (k[3] not in ("live", "not_applicable"))}
    if non_ideal:
        print(f"\n[replay_report] WARNING: {sum(non_ideal.values())} decisions are not (status=PASS, authz_mode in live/not_applicable):")
        for k, v in sorted(non_ideal.items()):
            print(f"  {k}: {v}")
    else:
        print("\n[replay_report] all replayed decisions: status=PASS and authz_replay_mode in {live, not_applicable}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
