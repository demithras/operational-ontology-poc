#!/usr/bin/env python3
"""`make reevaluate DECISION_ID=<id>` — the counterfactual
`reevaluate --decision D --under current` command docs/experiment/spec/07_versioning_and_replay.md
requires as a SEPARATE command from replay ("It must never overwrite or be
confused with historical replay"). Never writes anything back.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from seed import db_env  # noqa: E402
from services.decision_service.replay import DecisionNotFound, reevaluate_under_current  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1]:
        print("usage: reevaluate_cli.py <DECISION_ID>", file=sys.stderr)
        return 2
    decision_id = sys.argv[1]

    db_env.load_dotenv()
    conn = psycopg.connect(db_env.ontology_hot_dsn())
    try:
        try:
            result = reevaluate_under_current(decision_id, conn, db_env.opa_base_url())
        except DecisionNotFound as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    finally:
        conn.close()

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
