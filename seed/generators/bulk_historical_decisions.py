#!/usr/bin/env python3
"""Phase 7b BULK historical corpus generator (docs/experiment/briefs/phase7b.md
item C — fixes defect 2 of the orchestrator's Phase 7 verification: "bulk
records are inconsistent — synthetic gate outcomes that contradict the real
historical rules").

Same shape as the original Phase 7 script (writes DIRECTLY via
services/decision_service/rdf_writer.write_decision +
services/decision_service/store.insert_decision — the identical functions
propose_flow.py calls, never a second parallel writer — with
SELF-CONSISTENT synthetic evidence, randomly distributed across the REAL
archived v1/v2/v3 contract eras), but the gate OUTCOMES are no longer
randomly assigned: every record's authorization is a REAL OpenFGA `Check`
(era-pinned `authorization_model_id`, live store, real tuples — the exact
same services/decision_service/authz.py::check() propose_flow.py calls,
which also auto-captures the tuple snapshot replay needs) and every
record's policy is a REAL `opa eval` (era-pinned package, via the live OPA
server's REST API, services/decision_service/policy.py::evaluate()) against
the fabricated-but-internally-consistent evidence — never a value that
contradicts what the system's own gates would say. `context["origin"]`
records "bulk-evaluated" (vs "live" for seed/generators/historical_corpus.py's
real-HTTP-through-decision_service records) so provenance is queryable
independent of the `is_bulk_generated`/`D-BULK` decision_id-prefix markers,
which stay for backward-compatible detection.

Honest scope note, still true (unchanged from Phase 7): this does NOT go
through the real decision_service HTTP API, and does NOT run a real
Temporal/WMS execution — so the terminal, POST-approval execution outcome
(OBSERVED_SUCCESS/DIVERGED/OUTCOME_UNKNOWN/EXECUTION_FAILED) is still a
plausible label, drawn AFTER a real "allow" policy outcome, never itself
verified against a real action run. Nothing in `services/decision_service/replay.py`
checks that label against anything (only the gates — evidence hash, decision
content hash, authorization outcome, policy outcome — are re-verified), so
this remains honest: no field in this corpus is a record the system's own
replay refutes.

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
from services.decision_service import authz, policy as policy_mod, rdf_writer, store  # noqa: E402
from services.decision_service.action_types import get_action_type  # noqa: E402
from services.decision_service.evidence import EvidenceResult  # noqa: E402
from services.decision_service.manifest import build_manifest, content_addressed  # noqa: E402
from services.decision_service.models import DecisionRecord  # noqa: E402

# Every contract "era" this experiment actually published, oldest first —
# each entry is a full deployed_version.json-shaped map so build_manifest()
# reconstructs the EXACT archived manifest for that era (never "current"),
# INCLUDING the era's real, immutable-by-id OpenFGA authorization_model_id
# (contracts/manifests/openfga_model_ids.json) and real policy package name
# (contracts/actions/<dir>/transfer_inventory.yaml -> policy.package).
ERAS = [
    {"ontology": "v1", "shapes": "v1", "actions": "v1", "policies": "v1", "authorization": "v1", "identity": "v1", "projections": "v1", "reconciliation": "v1"},
    {"ontology": "v2", "shapes": "v2", "actions": "v2", "policies": "v2", "authorization": "v1", "identity": "v1", "projections": "v2", "reconciliation": "v1"},
    {"ontology": "v2", "shapes": "v2", "actions": "v3", "policies": "v2", "authorization": "v2", "identity": "v1", "projections": "v2", "reconciliation": "v1"},
]

ACTION_NAME = "transfer_inventory"
# NOT "every one of these is granted can_transfer_inventory" — model.fga
# defines it as `planner or junior_planner or agent_grant` and supervisor-1
# only ever holds `supervisor`/`senior_approver` (approval authority, never
# transfer authority itself), so a real Check for supervisor-1 legitimately
# comes back DENIED. Left in deliberately: it is real, correct system
# behavior (the real authz.check() call decides, never assumed), and adds
# natural DENIED_AUTHORIZATION diversity beyond the dedicated intent bucket
# below without a separate code path.
AUTHORIZED_ACTORS = ["planner-1", "junior-1", "supervisor-1"]
UNAUTHORIZED_ACTOR = "outsider-1"  # no tuple grants this actor anything — real DENIED
WAREHOUSES = [("WH-B", "WH-A"), ("WH-A", "WH-B")]

# Which "intent" bucket to engineer evidence for, weighted the same way the
# original bulk script's STATUSES_WEIGHTED approximated the historical mix
# (spec: "successful, denied, failed, diverged, and unknown outcomes
# represented"). The bucket only sets up INPUTS — every gate OUTCOME is the
# real evaluation's own answer, never assumed.
INTENT_WEIGHTED = [
    ("insufficient_evidence", 5),
    ("denied_authorization", 5),
    ("denied_policy", 8),
    ("executed_chain", 82),
]
# Within "executed_chain", once the REAL policy outcome comes back "allow"
# (no approval needed), a downstream execution-outcome label is drawn —
# never itself re-verified by replay (see module docstring).
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
    """Union of every field EITHER v1's or v2+'s policy.build_input() reads
    (services/decision_service/policy.py) — `available` for v1,
    `on_hand`/`reserved`/top-level `reservation_ok` for v2+ — so the SAME
    fact set is valid input regardless of which era's action is used."""
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
    part = f"PX-BULK{seq:05d}"
    source, dest = rng.choice(WAREHOUSES)
    created_at = base_time + timedelta(seconds=seq * 3)
    intent = _weighted_choice(rng, INTENT_WEIGHTED)

    action_name = ACTION_NAME
    action = get_action_type(action_name, era["actions"])
    action_meta = manifest["actions"][action_name]
    authz_model_id = manifest["openfga"].get("authorization_model_id")

    record = DecisionRecord(
        decision_id=f"D-BULK{uuid.uuid4().hex[:16]}",
        decision_type=action_name,
        actor_type="user",
        actor_id=UNAUTHORIZED_ACTOR if intent == "denied_authorization" else rng.choice(AUTHORIZED_ACTORS),
        action_type=action_name,
        action_version=action_meta["version"],
        action_pinned_sha256=action_meta["sha256"],
        action_version_dir=era["actions"],
        parameters={"source_warehouse": source, "destination_warehouse": dest, "part": part, "quantity": 10},
        context={"is_bulk_generated": True, "origin": "bulk-evaluated"},
        created_at=created_at,
        status="DRAFT",
        ontology_version=content_addressed(manifest["ontology"]),
        shape_set_version=content_addressed(manifest["shapes"]),
        authorization_model_version=content_addressed(manifest["openfga"]),
        policy_bundle_version=content_addressed(manifest["opa"]),
        identity_mapping_version=content_addressed(manifest["identity"]),
        projection_definition_version=content_addressed(manifest["projections"]),
        reconciliation_predicate_version=content_addressed(manifest["reconciliation"]),
        openfga_authorization_model_id=authz_model_id,
        evidence_snapshot_id=f"ES-BULK{uuid.uuid4().hex[:16]}",
    )

    if intent == "insufficient_evidence":
        # Never runs a gate at all — matches propose_flow.py's own
        # short-circuit (F02: "missing evidence") and replay's
        # authz_replay_mode == "not_applicable" treatment.
        record.evidence = EvidenceResult(
            facts_used={}, facts_excluded={}, missing=["current_source_inventory"], observed_at=created_at,
            source_positions=[{"system": "wms", "table": "inventory_lots", "pk": f"LOT-BULK-{seq}", "lsn": str(seq), "version": "1", "observed_at": created_at.isoformat()}],
        )
        record.status = "INSUFFICIENT_EVIDENCE"
        return record

    if intent == "denied_authorization":
        on_hand, reserved, quantity = 200, 0, 10
    elif intent == "denied_policy":
        # Proven combo (seed/generators/historical_corpus.py): remaining =
        # 30 - 25 = 5, below both v1's (10) and v2's (15) safety stock ->
        # real hard_deny in both eras' rego, uniformly.
        on_hand, reserved, quantity = 30, 0, 25
    else:  # executed_chain
        on_hand, reserved = 300, 0
        quantity = 20 + (seq % 7) * 15  # 20..110 — spans below/above both eras' approval thresholds

    record.parameters["quantity"] = quantity
    facts_used = _base_facts(on_hand, reserved, safety_stock=15, created_at=created_at)
    record.evidence = EvidenceResult(
        facts_used=facts_used, facts_excluded={}, source_positions=[
            {"system": "wms", "table": "inventory_lots", "pk": f"LOT-BULK-{seq}", "lsn": str(seq), "version": "1", "observed_at": created_at.isoformat()},
        ],
        projection_row_hashes=[uuid.uuid4().hex], observed_at=created_at,
    )

    # --- REAL authorization check (never fabricated) ---------------------
    object_ref = authz.resolve_object(action, record.parameters, record.evidence)
    record.authz_result = authz.check(
        openfga_api_url, store_id, action.authorization_relation, object_ref,
        record.actor_type, record.actor_id, authz_model_id,
    )
    if not record.authz_result.allowed:
        record.status = "DENIED_AUTHORIZATION"
        return record

    # --- REAL policy evaluation (never fabricated) ------------------------
    input_json = policy_mod.build_input(action, record.parameters, record.evidence)
    record.policy_result = policy_mod.evaluate(opa_base_url, action, input_json)
    outcome = record.policy_result.outcome
    if outcome == policy_mod.DENY:
        record.status = "DENIED_POLICY"
        return record
    if outcome not in (policy_mod.REQUIRE_APPROVAL, policy_mod.ALLOW):
        # OPA UNAVAILABLE — should not happen against a live server; fail
        # the record loudly rather than fabricate a status (never fake
        # success, common.md).
        raise RuntimeError(f"OPA policy evaluation UNAVAILABLE for {record.decision_id}: {record.policy_result.detail}")

    # propose_flow.py computes decision_content_hash for BOTH
    # REQUIRES_APPROVAL and APPROVED (it is set once, before branching on
    # outcome) — mirrored exactly here, never only for the allow branch.
    from services.decision_service.hashing import decision_content_hash

    record.decision_content_hash = decision_content_hash(
        record.actor_type, record.actor_id, record.principal_actor_id, record.evidence_snapshot_id,
        record.ontology_version, record.shape_set_version, record.authorization_model_version,
        record.policy_bundle_version, record.action_type, record.action_version, record.parameters,
    )
    if outcome == policy_mod.REQUIRE_APPROVAL:
        record.status = "REQUIRES_APPROVAL"  # left open, never auto-approved (bulk doesn't simulate approval)
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
            record = _build_record(rng, seq, era, manifest, base_time, openfga_api_url, store_id, opa_base_url)
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
