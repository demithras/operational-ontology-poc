#!/usr/bin/env python3
"""`make replay DECISION_ID=<id>` (docs/experiment/spec/07_versioning_and_replay.md
"Replay output"). Host-side CLI — connects directly (seed/db_env.py's
host-mapped ports), same pattern as services/projection_builder/rebuild.py —
calls the EXACT SAME services/decision_service/replay.py::replay_decision
the POST /replay/{id} HTTP endpoint uses, so the CLI and the API can never
silently diverge.

Prints the YAML-shaped replay output (spec 07's exact structure) to stdout.
Exit code 0 on PASS, 1 on FAIL, 2 on a hard error (decision not found, or
F29's ReplayIntegrityError — "replay fails loudly").
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402
import yaml  # noqa: E402

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.decision_service.replay import DecisionNotFound, ReplayIntegrityError, replay_decision  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1]:
        print("usage: replay_cli.py <DECISION_ID>", file=sys.stderr)
        return 2
    decision_id = sys.argv[1]

    db_env.load_dotenv()
    conn = psycopg.connect(db_env.ontology_hot_dsn())
    rdf4j_client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    try:
        try:
            result = replay_decision(decision_id, conn, rdf4j_client, db_env.openfga_api_url())
        except DecisionNotFound as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except ReplayIntegrityError as exc:
            print(f"F29 — replay fails loudly: {exc}", file=sys.stderr)
            return 2
    finally:
        rdf4j_client.close()
        conn.close()

    print(yaml.safe_dump(result.as_dict(), sort_keys=False, default_flow_style=False))
    return 0 if result.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
