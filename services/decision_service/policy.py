"""OPA policy gate — docs/experiment/spec/06_decision_and_action_runtime.md
"policy = opa.evaluate(exact decision input); persist policy input hash +
result + bundle version"; F05/F06/F24.

Fails CLOSED (F24: "OPA unavailable -> gate -> fail closed unless action
explicitly classified otherwise" — no ActionType in this repo opts out).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from services.decision_service.action_types import ActionType
from services.decision_service.evidence import EvidenceResult

ALLOW = "allow"
DENY = "deny"
REQUIRE_APPROVAL = "require_approval"
UNAVAILABLE = "UNAVAILABLE"


@dataclass
class PolicyEvalResult:
    outcome: str
    reasons: list[str]
    obligations: list[dict]
    input_json: dict
    input_hash: str
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    detail: str | None = None


def build_input(action: ActionType, parameters: dict, evidence: EvidenceResult) -> dict:
    if action.name == "transfer_inventory":
        src = evidence.facts_used["current_source_inventory"]
        dest = evidence.facts_used["current_destination_compatibility"]
        if action.version_dir == "v1":
            return {
                "parameters": {"quantity": parameters["quantity"]},
                "evidence": {
                    "source_available": src["available"],
                    "safety_stock": evidence.facts_used["safety_stock"],
                    "freshness_status": src["freshness_status"],
                    "source_quality_status": src["quality_status"],
                    "destination_quality_status": dest["quality_status"],
                },
                "config": {"approval_threshold_units": action.policy_config["approval_threshold_units"]},
            }
        # V2+ (docs/experiment/spec/07_versioning_and_replay.md): on_hand/
        # reserved/reservation_ok replace the retired `available` field —
        # see contracts/policies/v2/transfer_inventory.rego's input contract.
        return {
            "parameters": {"quantity": parameters["quantity"]},
            "evidence": {
                "on_hand": src["on_hand"],
                "reserved": src["reserved"],
                "reservation_ok": evidence.facts_used["reservation_ok"],
                "safety_stock": evidence.facts_used["safety_stock"],
                "freshness_status": src["freshness_status"],
                "source_quality_status": src["quality_status"],
                "destination_quality_status": dest["quality_status"],
            },
            "config": {"approval_threshold_units": action.policy_config["approval_threshold_units"]},
        }
    if action.name == "expedite_purchase_order":
        return {
            "parameters": {"expedite_fee": parameters["expedite_fee"]},
            "evidence": {"po_status": evidence.facts_used["current_po_status"]["po_status"]},
            "config": {"approval_threshold_cost": action.policy_config["approval_threshold_cost"]},
        }
    if action.name == "reschedule_work_order":
        wo = evidence.facts_used["current_work_order_status"]
        return {"evidence": {"work_order_status": wo["work_order_status"], "priority": wo["priority"]}}
    raise ValueError(f"no policy-input builder for action type {action.name!r}")


def _input_hash(input_json: dict) -> str:
    canonical = json.dumps(input_json, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def evaluate(opa_base_url: str, action: ActionType, input_json: dict) -> PolicyEvalResult:
    package_path = action.policy_package.replace(".", "/")
    input_hash = _input_hash(input_json)
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(f"{opa_base_url}/v1/data/{package_path}/result", json={"input": input_json})
        if r.status_code != 200:
            return PolicyEvalResult(
                outcome=UNAVAILABLE, reasons=[], obligations=[], input_json=input_json,
                input_hash=input_hash, detail=f"HTTP {r.status_code}: {r.text[:300]}",
            )
        body = r.json().get("result")
        if not body or "decision" not in body:
            # OPA up but the package/rule produced no result at all (e.g. a
            # bundle mismatch) — same fail-closed treatment as unreachable.
            return PolicyEvalResult(
                outcome=UNAVAILABLE, reasons=[], obligations=[], input_json=input_json,
                input_hash=input_hash, detail="OPA returned no result for package",
            )
        return PolicyEvalResult(
            outcome=body["decision"],
            reasons=body.get("reasons", []),
            obligations=body.get("obligations", []),
            input_json=input_json,
            input_hash=input_hash,
        )
    except httpx.HTTPError as exc:
        return PolicyEvalResult(
            outcome=UNAVAILABLE, reasons=[], obligations=[], input_json=input_json,
            input_hash=input_hash, detail=str(exc),
        )
