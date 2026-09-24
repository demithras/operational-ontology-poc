#!/usr/bin/env python3
"""Baseline-variant twin of seed/generators/bulk_historical_decisions.py
(Phase 10b item 4: "Load benchmark at full seed sizes (5,000 historical
decisions)... A/B rerun — all inside make experiment"). Writes DIRECTLY via
services.baseline.store.insert_decision (the identical function
services/baseline/propose_flow.py calls) with self-consistent synthetic
evidence spanning the real archived policy/authorization eras — same
"REAL authorization/policy gate, fabricated-but-consistent evidence"
design as the ontology's own bulk generator, minus anything RDF/SHACL
(this variant has none). `context["origin"] = "bulk-evaluated"`, decision
ids prefixed `B-BULK...` so provenance is queryable and never conflated
with the live-HTTP corpus (seed/generators/baseline_historical_corpus.py).

Usage:
    .venv/bin/python seed/generators/bulk_historical_decisions_baseline.py --target 5000 --seed 42
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
from services.baseline import hashing, store  # noqa: E402
from services.baseline.manifest import build_baseline_manifest  # noqa: E402
from services.baseline.models import DecisionRecord  # noqa: E402
from services.decision_service import authz, policy as policy_mod  # noqa: E402
from services.decision_service.action_types import get_action_type  # noqa: E402
from services.decision_service.evidence import EvidenceResult  # noqa: E402

# Same three eras as seed/generators/bulk_historical_decisions.py — only
# the policies/authorization/identity/actions keys matter here
# (services/baseline/manifest.build_baseline_manifest reads those four).
ERAS = [
    {"actions": "v1", "policies": "v1", "authorization": "v1", "identity": "v1"},
    {"actions": "v2", "policies": "v2", "authorization": "v1", "identity": "v1"},
    {"actions": "v3", "policies": "v2", "authorization": "v2", "identity": "v1"},
]

ACTION_NAME = "transfer_inventory"
AUTHORIZED_ACTORS = ["planner-1", "junior-1", "supervisor-1"]
UNAUTHORIZED_ACTOR = "outsider-1"
WAREHOUSES = [("WH-B", "WH-A"), ("WH-A", "WH-B")]

INTENT_WEIGHTED = [
    ("insufficient_evidence", 5),
    ("denied_authorization", 5),
    ("denied_policy", 8),
    ("executed_chain", 82),
]
EXECUTION_LABEL_WEIGHTED = [
    ("APPROVED", 20), ("OBSERVED_SUCCESS", 45), ("DIVERGED", 6),
    ("OUTCOME_UNKNOWN", 6), ("EXECUTION_FAILED", 2),
]


def _weighted_choice(rng: random.Random, weighted: list[tuple[str, int]]) -> str:
    total = sum(w for _, w in weighted)
    pick = rng.uniform(0, total)
    upto = 0.0
    for value, weight in weighted:
        upto += weight
        if upto >= pick:
            return value
    return weighted[-1][0]


def _base_facts(on_hand: int, reserved: int, safety_stock: int, created_at: datetime) -> dict:
    return {
        "current_source_inventory": {
            "on_hand": on_hand, "reserved": reserved, "available": on_hand - reserved,
            "quality_status": "OK", "freshness_status": "FRESH", "as_of": created_at.isoformat(),
        },
        "current_destination_compatibility": {"exists": True, "quality_status": "OK"},
        "safety_stock": safety_stock,
        "reservation_ok": on_hand >= reserved,
        "route_protection": {"status": "NOT_APPLICABLE", "work_order_ids": []},
    }


def _build_record(
    rng: random.Random, seq: int, era: dict, manifest: dict, base_time: datetime,
    openfga_api_url: str, store_id: str | None, opa_base_url: str,
) -> DecisionRecord:
    part = f"PX-BASEBULK{seq:05d}"
    source, dest = rng.choice(WAREHOUSES)
    created_at = base_time + timedelta(seconds=seq * 3)
    intent = _weighted_choice(rng, INTENT_WEIGHTED)

    action = get_action_type(ACTION_NAME, era["actions"])
    action_meta = manifest["actions"][ACTION_NAME]
    authz_model_id = manifest["openfga"].get("authorization_model_id")

    from services.decision_service.manifest import content_addressed

    record = DecisionRecord(
        decision_id=f"B-BULK{uuid.uuid4().hex[:16]}",
        decision_type=ACTION_NAME,
        actor_type="user",
        actor_id=UNAUTHORIZED_ACTOR if intent == "denied_authorization" else rng.choice(AUTHORIZED_ACTORS),
        action_type=ACTION_NAME,
        action_version=action_meta["version"],
        action_pinned_sha256=action_meta["sha256"],
        action_version_dir=era["actions"],
        parameters={"source_warehouse": source, "destination_warehouse": dest, "part": part, "quantity": 10},
        context={"is_bulk_generated": True, "origin": "bulk-evaluated"},
        created_at=created_at,
        status="DRAFT",
        authorization_model_version=content_addressed(manifest["openfga"]),
        policy_bundle_version=content_addressed(manifest["opa"]),
        identity_mapping_version=content_addressed(manifest["identity"]),
        openfga_authorization_model_id=authz_model_id,
        evidence_snapshot_id=f"ES-BASEBULK{uuid.uuid4().hex[:16]}",
    )

    if intent == "insufficient_evidence":
        record.evidence = EvidenceResult(
            facts_used={}, facts_excluded={}, missing=["current_source_inventory"], observed_at=created_at,
            source_positions=[{"system": "wms", "table": "inventory_lots", "pk": f"LOT-BASEBULK-{seq}", "lsn": str(seq), "version": "1", "observed_at": created_at.isoformat()}],
        )
        record.status = "INSUFFICIENT_EVIDENCE"
        return record

    if intent == "denied_authorization":
        on_hand, reserved, quantity = 200, 0, 10
    elif intent == "denied_policy":
        on_hand, reserved, quantity = 30, 0, 25
    else:
        on_hand, reserved = 300, 0
        quantity = 20 + (seq % 7) * 15

    record.parameters["quantity"] = quantity
    facts_used = _base_facts(on_hand, reserved, safety_stock=15, created_at=created_at)
    record.evidence = EvidenceResult(
        facts_used=facts_used, facts_excluded={}, source_positions=[
            {"system": "wms", "table": "inventory_lots", "pk": f"LOT-BASEBULK-{seq}", "lsn": str(seq), "version": "1", "observed_at": created_at.isoformat()},
        ],
        projection_row_hashes=[uuid.uuid4().hex], observed_at=created_at,
    )

    object_ref = authz.resolve_object(action, record.parameters, record.evidence)
    record.authz_result = authz.check(
        openfga_api_url, store_id, action.authorization_relation, object_ref,
        record.actor_type, record.actor_id, authz_model_id,
    )
    if not record.authz_result.allowed:
        record.status = "DENIED_AUTHORIZATION"
        return record

    input_json = policy_mod.build_input(action, record.parameters, record.evidence)
    record.policy_result = policy_mod.evaluate(opa_base_url, action, input_json)
    outcome = record.policy_result.outcome
    if outcome == policy_mod.DENY:
        record.status = "DENIED_POLICY"
        return record
    if outcome not in (policy_mod.REQUIRE_APPROVAL, policy_mod.ALLOW):
        raise RuntimeError(f"OPA policy evaluation UNAVAILABLE for {record.decision_id}: {record.policy_result.detail}")

    record.decision_content_hash = hashing.decision_content_hash(
        record.actor_type, record.actor_id, record.principal_actor_id, record.evidence_snapshot_id,
        record.authorization_model_version, record.policy_bundle_version, record.action_type, record.action_version, record.parameters,
    )
    if outcome == policy_mod.REQUIRE_APPROVAL:
        record.status = "REQUIRES_APPROVAL"
    else:
        record.status = _weighted_choice(rng, EXECUTION_LABEL_WEIGHTED)
    return record


def generate(target: int, seed: int, batch_commit: int = 200) -> dict:
    db_env.load_dotenv()
    rng = random.Random(seed)
    openfga_api_url = db_env.openfga_api_url()
    opa_base_url = db_env.opa_base_url()
    store_id = authz.resolve_store_id(openfga_api_url)
    if store_id is None:
        raise RuntimeError(f"could not resolve the OpenFGA store at {openfga_api_url} — is `make up` running?")

    with psycopg.connect(db_env.baseline_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM decisions")
            existing = cur.fetchone()[0]
    to_generate = max(0, target - existing)
    print(f"[bulk-baseline] {existing} decisions already exist; generating {to_generate} more toward target={target}")
    if to_generate == 0:
        return {"existing": existing, "generated": 0, "target": target}

    conn = psycopg.connect(db_env.baseline_dsn())
    base_time = datetime.now(timezone.utc) - timedelta(days=180)
    era_counts = {i: 0 for i in range(len(ERAS))}
    committed = 0
    try:
        for seq in range(to_generate):
            era_idx = seq % len(ERAS)
            era = ERAS[era_idx]
            manifest = build_baseline_manifest(version=era)
            record = _build_record(rng, seq, era, manifest, base_time, openfga_api_url, store_id, opa_base_url)
            store.insert_decision(conn, record)
            era_counts[era_idx] += 1
            committed += 1
            if committed % batch_commit == 0:
                print(f"[bulk-baseline] {committed}/{to_generate} written")
    finally:
        conn.close()

    return {"existing": existing, "generated": committed, "target": target, "era_counts": era_counts}


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
