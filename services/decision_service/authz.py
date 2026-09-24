"""OpenFGA authorization gate — docs/experiment/spec/06_decision_and_action_runtime.md
"authz = openfga.check(actor, requested capability, target)"; F03/F04/F23.

Fails CLOSED (F23: "OpenFGA unavailable -> gate -> fail closed for
protected action") — any connection error, timeout, or non-2xx response
that isn't a well-formed {"allowed": ...} answer is treated the same as
DENIED, distinguished only by `outcome == "UNAVAILABLE"` so the caller can
tell "actually denied" apart from "couldn't ask" (acceptance criterion 11:
"explicit unavailable/pending/unknown state, not fabricated certainty").

contracts/authorization/v1/model.fga only defines relations on the
`warehouse` type (matching 03_domain_scenario.md's region/warehouse
authority scoping) — all three ActionTypes therefore bind authorization to
A WAREHOUSE, resolved differently per action: transfer_inventory uses its
own `source_warehouse` parameter directly; expedite_purchase_order and
reschedule_work_order resolve the relevant warehouse from evidence gathered
by services/decision_service/evidence.py (a PO's first line's destination,
a work order's own warehouse) rather than needing separate `purchase_order`/
`work_order` FGA types — one authorization model, not three.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from services.decision_service.action_types import ActionType
from services.decision_service.evidence import EvidenceResult

ALLOWED = "ALLOWED"
DENIED = "DENIED"
UNAVAILABLE = "UNAVAILABLE"


@dataclass
class AuthzResult:
    outcome: str
    relation: str
    object: str
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    detail: str | None = None

    @property
    def allowed(self) -> bool:
        return self.outcome == ALLOWED


def resolve_object(action: ActionType, parameters: dict, evidence: EvidenceResult) -> str:
    """Returns the `warehouse:<id>` object string to check authority against."""
    if action.name == "transfer_inventory":
        return f"warehouse:{parameters['source_warehouse']}"
    if action.name == "expedite_purchase_order":
        warehouse = evidence.facts_used.get("current_po_status", {}).get("destination_warehouse")
        return f"warehouse:{warehouse}"
    if action.name == "reschedule_work_order":
        warehouse = evidence.facts_used.get("current_work_order_status", {}).get("warehouse")
        return f"warehouse:{warehouse}"
    raise ValueError(f"no authorization-object resolver for action type {action.name!r}")


def _actor_fga_id(actor_type: str, actor_id: str) -> str:
    return f"{actor_type}:{actor_id}"


def check(
    openfga_api_url: str,
    store_id: str,
    relation: str,
    object_ref: str,
    actor_type: str,
    actor_id: str,
) -> AuthzResult:
    tuple_key = {"user": _actor_fga_id(actor_type, actor_id), "relation": relation, "object": object_ref}
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(f"{openfga_api_url}/stores/{store_id}/check", json={"tuple_key": tuple_key})
        if r.status_code != 200:
            return AuthzResult(outcome=UNAVAILABLE, relation=relation, object=object_ref, detail=f"HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        outcome = ALLOWED if body.get("allowed") else DENIED
        return AuthzResult(outcome=outcome, relation=relation, object=object_ref)
    except httpx.HTTPError as exc:
        return AuthzResult(outcome=UNAVAILABLE, relation=relation, object=object_ref, detail=str(exc))


def resolve_principal(openfga_api_url: str, store_id: str, agent_id: str) -> str | None:
    """H1 'actor delegation context if an agent acts for a human' /
    F32 ('agent impersonates human ... impossible without explicit
    delegation') — the principal is RESOLVED from OpenFGA's own tuples
    (contracts/authorization/v1/model.fga's agent#principal relation), never
    trusted from a caller-supplied field on the propose request, so a
    request cannot simply CLAIM to be acting for an arbitrary human."""
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(
                f"{openfga_api_url}/stores/{store_id}/read",
                json={"tuple_key": {"object": f"agent:{agent_id}", "relation": "principal"}},
            )
        r.raise_for_status()
        tuples = r.json().get("tuples", [])
        if not tuples:
            return None
        user_ref = tuples[0]["key"]["user"]  # "user:planner-1"
        return user_ref.split(":", 1)[1] if ":" in user_ref else user_ref
    except httpx.HTTPError:
        return None


def resolve_store_id(openfga_api_url: str, store_name: str = "oo-poc") -> str | None:
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{openfga_api_url}/stores")
        r.raise_for_status()
        for store in r.json().get("stores", []):
            if store["name"] == store_name:
                return store["id"]
    except httpx.HTTPError:
        return None
    return None
