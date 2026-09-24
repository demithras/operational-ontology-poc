#!/usr/bin/env python3
"""Phase 7 BULK historical corpus generator (docs/experiment/spec/07_versioning_and_replay.md
"bulk-generate records up to 5,000 total historical decisions for query/
load tests"). Runs AFTER seed/generators/historical_corpus.py's LIVE V1/V2
generation and after `make deploy-v3` — see docs/experiment/implementation-notes.md
Phase 7 section for the exact sequence.

Honest scope note (documented, per common.md "never fake success"):
these decisions are NOT proposed through the real decision_service HTTP
API/gates — that would make 5,000 records take far too long for a POC
(the live generator averages ~0.7s/decision even with 8-way concurrency).
Instead this writes DIRECTLY via the SAME production write path
(services/decision_service/rdf_writer.write_decision +
services/decision_service/store.insert_decision — the identical functions
propose_flow.py calls, never a second parallel writer), with SELF-CONSISTENT
synthetic evidence/gate results built from the SAME hashing functions real
decisions use, and randomly distributed across the REAL archived v1/v2/v3
contract pins so the resulting corpus is a realistic-shaped population for
query/load testing — but the gate DECISIONS themselves (allow/deny/
require_approval) are randomly assigned, not derived from evaluating real
policy against the fabricated evidence. `is_bulk_generated=true` is stamped
into every record's context so query code can always tell live from bulk.

Usage:
    .venv/bin/python seed/generators/bulk_historical_decisions.py --target 5000 --seed 42
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402

from seed import db_env  # noqa: E402
from services.common.rdf4j_client import RDF4JClient  # noqa: E402
from services.decision_service import rdf_writer, store  # noqa: E402
from services.decision_service.authz import AuthzResult  # noqa: E402
from services.decision_service.evidence import EvidenceResult  # noqa: E402
from services.decision_service.manifest import build_manifest, content_addressed  # noqa: E402
from services.decision_service.models import DecisionRecord  # noqa: E402
from services.decision_service.policy import PolicyEvalResult  # noqa: E402

# Every contract "era" this experiment actually published, oldest first —
# each entry is a full deployed_version.json-shaped map so build_manifest()
# reconstructs the EXACT archived manifest for that era (never "current").
ERAS = [
    {"ontology": "v1", "shapes": "v1", "actions": "v1", "policies": "v1", "authorization": "v1", "identity": "v1", "projections": "v1", "reconciliation": "v1"},
    {"ontology": "v2", "shapes": "v2", "actions": "v2", "policies": "v2", "authorization": "v1", "identity": "v1", "projections": "v2", "reconciliation": "v1"},
    {"ontology": "v2", "shapes": "v2", "actions": "v3", "policies": "v2", "authorization": "v2", "identity": "v1", "projections": "v2", "reconciliation": "v1"},
]

STATUSES_WEIGHTED = [
    ("APPROVED", 20), ("OBSERVED_SUCCESS", 45), ("REQUIRES_APPROVAL", 3),
    ("DENIED_POLICY", 8), ("DENIED_AUTHORIZATION", 5), ("INSUFFICIENT_EVIDENCE", 5),
    ("DIVERGED", 6), ("OUTCOME_UNKNOWN", 6), ("EXECUTION_FAILED", 2),
]
ACTORS = ["planner-1", "junior-1", "supervisor-1", "bulk-planner-2", "bulk-planner-3"]
WAREHOUSES = [("WH-B", "WH-A"), ("WH-A", "WH-B")]


def _weighted_choice(rng: random.Random, weighted: list[tuple[str, int]]) -> str:
    total = sum(w for _, w in weighted)
    pick = rng.uniform(0, total)
    upto = 0.0
    for value, weight in weighted:
        upto += weight
        if upto >= pick:
            return value
    return weighted[-1][0]


def _build_record(rng: random.Random, seq: int, era: dict, manifest: dict, base_time: datetime) -> DecisionRecord:
    part = f"PX-BULK{seq:05d}"
    source, dest = rng.choice(WAREHOUSES)
    quantity = rng.randint(5, 150)
    on_hand = rng.randint(quantity, quantity + 500)
    reserved = rng.randint(0, min(20, on_hand))
    status = _weighted_choice(rng, STATUSES_WEIGHTED)
    created_at = base_time + timedelta(seconds=seq * 3)

    action_name = "transfer_inventory"
    action_meta = manifest["actions"][action_name]

    record = DecisionRecord(
        decision_id=f"D-BULK{uuid.uuid4().hex[:16]}",
        decision_type=action_name,
        actor_type="user",
        actor_id=rng.choice(ACTORS),
        action_type=action_name,
        action_version=action_meta["version"],
        action_pinned_sha256=action_meta["sha256"],
        action_version_dir=era["actions"],
        parameters={"source_warehouse": source, "destination_warehouse": dest, "part": part, "quantity": quantity},
        context={"is_bulk_generated": True},
        created_at=created_at,
        status=status,
        ontology_version=content_addressed(manifest["ontology"]),
        shape_set_version=content_addressed(manifest["shapes"]),
        authorization_model_version=content_addressed(manifest["openfga"]),
        policy_bundle_version=content_addressed(manifest["opa"]),
        identity_mapping_version=content_addressed(manifest["identity"]),
        projection_definition_version=content_addressed(manifest["projections"]),
        reconciliation_predicate_version=content_addressed(manifest["reconciliation"]),
        evidence_snapshot_id=f"ES-BULK{uuid.uuid4().hex[:16]}",
    )

    facts_used = {
        "current_source_inventory": {
            "on_hand": on_hand, "reserved": reserved, "available": on_hand - reserved,
            "quality_status": "OK", "freshness_status": "FRESH", "as_of": created_at.isoformat(),
        },
        "current_destination_compatibility": {"exists": True, "quality_status": "OK"},
        "safety_stock": rng.choice([10, 15, 50, 60]),
        "route_protection": {"status": "NOT_APPLICABLE", "work_order_ids": []},
    }
    record.evidence = EvidenceResult(
        facts_used=facts_used, facts_excluded={}, source_positions=[
            {"system": "wms", "table": "inventory_lots", "pk": f"LOT-BULK-{seq}", "lsn": str(seq), "version": "1", "observed_at": created_at.isoformat()},
        ],
        projection_row_hashes=[uuid.uuid4().hex],
        observed_at=created_at,
        missing=["source_available"] if status == "INSUFFICIENT_EVIDENCE" else [],
    )

    if status != "INSUFFICIENT_EVIDENCE":
        authz_outcome = "DENIED" if status == "DENIED_AUTHORIZATION" else "ALLOWED"
        record.authz_result = AuthzResult(outcome=authz_outcome, relation="can_transfer_inventory", object=f"warehouse:{source}", checked_at=created_at)
    if status not in ("INSUFFICIENT_EVIDENCE", "DENIED_AUTHORIZATION"):
        policy_outcome = {"DENIED_POLICY": "deny", "REQUIRES_APPROVAL": "require_approval"}.get(status, "allow")
        input_json = {
            "parameters": {"quantity": quantity},
            "evidence": {"source_available": on_hand - reserved, "safety_stock": facts_used["safety_stock"],
                         "freshness_status": "FRESH", "source_quality_status": "OK", "destination_quality_status": "OK"},
            "config": {"approval_threshold_units": 100},
        }
        record.policy_result = PolicyEvalResult(
            outcome=policy_outcome, reasons=[] if policy_outcome == "allow" else ["safety_stock_breach"],
            obligations=[], input_json=input_json, input_hash=uuid.uuid4().hex, evaluated_at=created_at,
        )
    if status in ("REQUIRES_APPROVAL",):
        pass  # left REQUIRES_APPROVAL, never auto-approved (bulk records don't simulate the approval step)
    return record


def generate(target: int, seed: int, batch_commit: int = 200) -> dict:
    db_env.load_dotenv()
    rng = random.Random(seed)

    with psycopg.connect(db_env.ontology_hot_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM decisions")
            existing = cur.fetchone()[0]
    to_generate = max(0, target - existing)
    print(f"[bulk] {existing} decisions already exist; generating {to_generate} more toward target={target}")
    if to_generate == 0:
        return {"existing": existing, "generated": 0, "target": target}

    rdf4j_client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    conn = psycopg.connect(db_env.ontology_hot_dsn())
    base_time = datetime.now(timezone.utc) - timedelta(days=180)
    era_counts = {i: 0 for i in range(len(ERAS))}
    committed_since_batch = 0
    try:
        for seq in range(to_generate):
            era_idx = seq % len(ERAS)  # round-robin across V1/V2/V3 eras, evenly
            era = ERAS[era_idx]
            manifest = build_manifest(version=era)
            record = _build_record(rng, seq, era, manifest, base_time)
            committed, detail = rdf_writer.write_decision(rdf4j_client, record)
            if not committed:
                print(f"  [bulk] SHACL rejection at seq={seq}: {detail[:300]}", file=sys.stderr)
                continue
            store.insert_decision(conn, record)
            era_counts[era_idx] += 1
            committed_since_batch += 1
            if committed_since_batch % batch_commit == 0:
                print(f"[bulk] {committed_since_batch}/{to_generate} written")
    finally:
        rdf4j_client.close()
        conn.close()

    return {"existing": existing, "generated": committed_since_batch, "target": target, "era_counts": era_counts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    result = generate(args.target, args.seed)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
