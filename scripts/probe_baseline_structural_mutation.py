#!/usr/bin/env python3
"""H11 like-for-like structural-validation probe (orchestrator correction,
Phase 10b): mutation-results.json's SHACL_CARDINALITY mutation shows the
ontology's SHACL sail rejects a Decision/EvidenceSnapshot write missing a
required field (`oo:snapshotContentHash`, cardinality 1 -> 0). H11 must
not credit the ontology with an advantage on that dimension without also
testing whether the baseline's OWN equivalent guard — the real Postgres
`evidence_snapshot JSONB NOT NULL` column constraint on `decisions`
(services/baseline/schema.sql) — provides the same protection, and what
happens when it's removed.

Live experiment, against the REAL running baseline_service + database
(never simulated):

  1. Create one real synthetic baseline decision (control).
  2. BEFORE mutation: attempt `UPDATE decisions SET evidence_snapshot =
     NULL` on it directly via raw SQL — expect Postgres to REJECT it
     (a real NOT NULL constraint violation) — the baseline's write-time
     guard working, structurally the same role SHACL plays for the
     ontology variant (reject a write missing required evidence), just
     coarser-grained (whole column vs one nested field).
  3. APPLY the mutation: `ALTER TABLE decisions ALTER COLUMN
     evidence_snapshot DROP NOT NULL` (drops the constraint entirely —
     the baseline's literal equivalent of SHACL_CARDINALITY's minCount
     1 -> 0).
  4. Retry the SAME UPDATE — now it succeeds (the "corrupted" write SHACL
     would have blocked at write time now goes through on this variant
     too).
  5. Run services/baseline/replay.replay_decision() on the now-corrupted
     row — check whether ANY downstream mechanism still catches it.
  6. REVERT: restore the original evidence_snapshot value AND re-add the
     NOT NULL constraint. Verify replay is PASS-like again post-revert.

Writes experiments/exp-000/results/baseline-structural-mutation-probe.json.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import httpx  # noqa: E402
import psycopg  # noqa: E402
from psycopg.types.json import Json  # noqa: E402

from seed import db_env  # noqa: E402
from services.baseline.replay import replay_decision  # noqa: E402

RESULTS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "baseline-structural-mutation-probe.json"


def _create_synthetic_decision() -> str:
    """One real transfer_inventory decision through the live baseline_service,
    disjoint synthetic id range (SKU-978xxx), never touching any shared range."""
    db_env.load_dotenv()
    wms = httpx.Client(base_url=db_env.http_base_urls()["wms"], timeout=15.0)
    dec = httpx.Client(base_url=db_env.baseline_service_url(), timeout=15.0)
    conn = psycopg.connect(db_env.ontology_hot_dsn())
    try:
        sku = f"SKU-978{uuid.uuid4().int % 1000:03d}"
        canonical = f"PX-{978000 + (uuid.uuid4().int % 1000):04d}"
        r = wms.post("/_test/inventory/set", json={"part": sku, "warehouse_id": "WH-B", "on_hand": 200, "reserved": 0, "quality_status": "OK"})
        r.raise_for_status()
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            with conn.cursor() as cur:
                cur.execute("SELECT on_hand FROM current_inventory WHERE part=%s AND warehouse=%s", (canonical, "WH-B"))
                row = cur.fetchone()
            conn.commit()
            if row and row[0] == 200:
                break
            time.sleep(0.5)
        resp = dec.post("/decisions/propose", json={
            "action_type": "transfer_inventory",
            "actor": {"type": "user", "id": "planner-1"},
            "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": canonical, "quantity": 10},
            "context": {"origin": "h11-structural-mutation-probe"},
        })
        resp.raise_for_status()
        return resp.json()["decision_id"]
    finally:
        wms.close()
        dec.close()
        conn.close()


def run() -> dict:
    db_env.load_dotenv()
    openfga_api_url = db_env.openfga_api_url()
    opa_base_url = db_env.opa_base_url()
    decision_id = _create_synthetic_decision()

    conn = psycopg.connect(db_env.baseline_dsn())
    conn.autocommit = False
    steps: list[dict] = []

    def replay_status() -> dict:
        conn2 = psycopg.connect(db_env.baseline_dsn())
        try:
            result = replay_decision(decision_id, conn2, openfga_api_url, opa_base_url)
            return {"status": result.status, "replay": result.replay}
        finally:
            conn2.close()

    control_before = replay_status()
    steps.append({"step": "control_replay_before_any_mutation", "result": control_before})

    # Save the original evidence_snapshot for a clean revert.
    with conn.cursor() as cur:
        cur.execute("SELECT evidence_snapshot FROM decisions WHERE decision_id = %s", (decision_id,))
        original_evidence_snapshot = cur.fetchone()[0]
    conn.commit()

    # Step 2: attempt the corrupting write BEFORE the mutation — expect a
    # real Postgres NOT NULL violation.
    rejected_before_mutation = False
    reject_detail = None
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE decisions SET evidence_snapshot = NULL WHERE decision_id = %s", (decision_id,))
        conn.commit()
    except psycopg.errors.NotNullViolation as exc:
        rejected_before_mutation = True
        reject_detail = str(exc)
        conn.rollback()
    steps.append({"step": "attempt_null_write_before_mutation", "rejected_by_db": rejected_before_mutation, "detail": reject_detail})

    # Step 3: apply the mutation (baseline's literal equivalent of
    # SHACL_CARDINALITY: drop the constraint that guards this field).
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE decisions ALTER COLUMN evidence_snapshot DROP NOT NULL")
    conn.commit()
    steps.append({"step": "mutation_applied", "detail": "ALTER TABLE decisions ALTER COLUMN evidence_snapshot DROP NOT NULL"})

    # Step 4: retry the same write — now it should succeed.
    write_succeeded_after_mutation = False
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE decisions SET evidence_snapshot = NULL WHERE decision_id = %s", (decision_id,))
        conn.commit()
        write_succeeded_after_mutation = True
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        steps.append({"step": "attempt_null_write_after_mutation_FAILED_UNEXPECTEDLY", "detail": f"{type(exc).__name__}: {exc}"})
    steps.append({"step": "attempt_null_write_after_mutation", "write_succeeded": write_succeeded_after_mutation})

    # Step 5: does ANY downstream mechanism (replay) still catch it?
    corrupted_replay = replay_status() if write_succeeded_after_mutation else None
    steps.append({"step": "replay_after_corruption", "result": corrupted_replay})
    replay_caught_it = bool(corrupted_replay and corrupted_replay["status"] not in ("PASS", "PASS_FAIL_CLOSED_VERIFIED"))

    # Step 6: revert both the data and the constraint.
    with conn.cursor() as cur:
        cur.execute("UPDATE decisions SET evidence_snapshot = %s WHERE decision_id = %s", (Json(original_evidence_snapshot), decision_id))
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE decisions ALTER COLUMN evidence_snapshot SET NOT NULL")
    conn.commit()
    steps.append({"step": "reverted", "detail": "evidence_snapshot restored, NOT NULL constraint re-added"})

    control_after_revert = replay_status()
    steps.append({"step": "control_replay_after_revert", "result": control_after_revert})
    revert_clean = control_after_revert["status"] in ("PASS", "PASS_FAIL_CLOSED_VERIFIED")

    conn.close()

    finding = (
        f"Baseline's write-time guard (Postgres NOT NULL on `decisions.evidence_snapshot`) "
        f"{'DID' if rejected_before_mutation else 'did NOT'} reject the corrupting write before the mutation "
        f"was applied — structurally the same role SHACL_CARDINALITY's target field plays for the ontology "
        f"variant (reject a write missing required evidence), coarser-grained (whole column, not one nested "
        f"field). After the mutation removed that guard, the write succeeded, and the baseline's OWN replay "
        f"mechanism {'DID' if replay_caught_it else 'did NOT'} independently catch the corruption via hash "
        f"mismatch (services/baseline/replay.py's evidence_hash_match check, which treats a missing "
        f"content_hash as an automatic mismatch). "
        f"{'The revert was clean.' if revert_clean else 'WARNING: the revert did not restore a clean PASS state.'}"
    )

    doc = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "decision_id": decision_id,
        "steps": steps,
        "rejected_before_mutation": rejected_before_mutation,
        "write_succeeded_after_mutation": write_succeeded_after_mutation,
        "replay_caught_it_after_mutation": replay_caught_it,
        "revert_clean": revert_clean,
        "finding": finding,
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    print(json.dumps(doc, indent=2, sort_keys=True))
    return doc


if __name__ == "__main__":
    raise SystemExit(0 if run()["revert_clean"] else 1)
