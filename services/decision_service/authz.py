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
    # Phase 7: the REAL OpenFGA authorization_model_id this specific check
    # was evaluated against (None only when the check itself couldn't run —
    # UNAVAILABLE). Recorded alongside the outcome so replay can re-issue
    # the IDENTICAL Check request (same model id, same tuple_key) later —
    # see services/decision_service/replay.py.
    model_id: str | None = None
    # Phase 7b (docs/adr/0004-openfga-historical-model-and-tuple-snapshot.md,
    # R4 ADR update): the FULL relationship-tuple set this store held at the
    # moment of this check ("the whole small tuple set hashed" — this
    # model's real tuple population is ~10 rows, cheap to snapshot whole
    # rather than trying to infer which subset was "relevant" to this one
    # Check's graph traversal). None when the snapshot read itself failed
    # (best-effort — never blocks the check outcome) or when this
    # AuthzResult IS a replay's own re-check (capture_tuples_snapshot=False
    # there, since replay is verifying a snapshot, not producing a new one).
    tuples_snapshot: list[dict] | None = None

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


def _read_all_tuples(openfga_api_url: str, store_id: str, page_limit: int = 20) -> list[dict] | None:
    """Phase 7b: the store's COMPLETE tuple population, canonicalized
    (sorted, `user`/`relation`/`object` only — drops OpenFGA's own
    `timestamp` so the snapshot is stable across re-reads of unchanged
    tuples). Used two ways: (1) captured onto every AuthzResult at
    propose() time so a Decision's authorization check carries the exact
    relationship state it was evaluated against, independent of whatever
    the LIVE store looks like later; (2) replayed back as `contextual_tuples`
    on the historical re-Check, so replay proves authorization against the
    HISTORICAL tuples, never today's — see
    docs/adr/0004-openfga-historical-model-and-tuple-snapshot.md.

    Best-effort: returns None (never raises) on any failure — a missing
    snapshot degrades that decision's replay to the honest
    `authz_replay_mode: "recorded_only"` fallback, never a hard error at
    propose time."""
    tuples: list[dict] = []
    continuation_token = ""
    try:
        with httpx.Client(timeout=5.0) as client:
            for _ in range(page_limit):
                body: dict = {}
                if continuation_token:
                    body["continuation_token"] = continuation_token
                r = client.post(f"{openfga_api_url}/stores/{store_id}/read", json=body)
                if r.status_code != 200:
                    return None
                payload = r.json()
                for row in payload.get("tuples", []):
                    key = row.get("key", {})
                    tuples.append({"user": key.get("user"), "relation": key.get("relation"), "object": key.get("object")})
                continuation_token = payload.get("continuation_token") or ""
                if not continuation_token:
                    break
    except httpx.HTTPError:
        return None
    return sorted(tuples, key=lambda t: (t["object"] or "", t["relation"] or "", t["user"] or ""))


def check(
    openfga_api_url: str,
    store_id: str,
    relation: str,
    object_ref: str,
    actor_type: str,
    actor_id: str,
    authorization_model_id: str | None = None,
    contextual_tuples: list[dict] | None = None,
    capture_tuples_snapshot: bool = True,
) -> AuthzResult:
    """Phase 7: `authorization_model_id`, when given, pins the Check to that
    EXACT model version (OpenFGA's real, documented Check API field) —
    models are immutable by id, so replaying a historical decision's
    authorization gate means re-issuing this SAME call with its OWN
    recorded model_id, never the store's current default (which would
    silently re-evaluate under whatever the LATEST model happens to be —
    exactly the "silently apply today's policy to yesterday's decision"
    07_versioning_and_replay.md forbids). Live proposals omit it and get
    OpenFGA's own "latest model in this store" default, matching Phase 5/6
    behavior exactly.

    Phase 7b: `contextual_tuples`, when given (replay only — see
    services/decision_service/replay.py), are passed as OpenFGA's own
    `contextual_tuples` Check field — additional tuples considered for THIS
    call only, never written to the store — so replay can re-issue the
    check against the HISTORICAL relationship snapshot even if the live
    store's tuples have since changed, without needing a second store or a
    tuple restore/rollback. `capture_tuples_snapshot` (default True) makes a
    normal (propose-time) call also read back the store's current full
    tuple population and attach it to the returned AuthzResult — set False
    for replay's own re-check, which is verifying a snapshot, not producing
    one."""
    tuple_key = {"user": _actor_fga_id(actor_type, actor_id), "relation": relation, "object": object_ref}
    body: dict = {"tuple_key": tuple_key}
    if authorization_model_id:
        body["authorization_model_id"] = authorization_model_id
    if contextual_tuples:
        body["contextual_tuples"] = {"tuple_keys": contextual_tuples}
    snapshot = _read_all_tuples(openfga_api_url, store_id) if (capture_tuples_snapshot and not contextual_tuples) else None
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.post(f"{openfga_api_url}/stores/{store_id}/check", json=body)
        if r.status_code != 200:
            return AuthzResult(
                outcome=UNAVAILABLE, relation=relation, object=object_ref,
                detail=f"HTTP {r.status_code}: {r.text[:300]}", model_id=authorization_model_id,
                tuples_snapshot=snapshot,
            )
        resp_body = r.json()
        outcome = ALLOWED if resp_body.get("allowed") else DENIED
        return AuthzResult(
            outcome=outcome, relation=relation, object=object_ref, model_id=authorization_model_id,
            tuples_snapshot=snapshot,
        )
    except httpx.HTTPError as exc:
        return AuthzResult(
            outcome=UNAVAILABLE, relation=relation, object=object_ref, detail=str(exc),
            model_id=authorization_model_id, tuples_snapshot=snapshot,
        )


def resolve_latest_authorization_model_id(openfga_api_url: str, store_id: str) -> str | None:
    """The store's newest authorization-model id (OpenFGA's
    `GET /stores/{id}/authorization-models` lists models newest-first —
    verified against the running openfga/openfga:latest image during
    implementation). Re-resolved fresh on every call (never cached), same
    self-healing rationale as resolve_store_id above: a migration
    (migrations/v2_to_v3/deploy.py) can write a brand-new model into this
    SAME store at any time, and the next propose() must start pinning it
    immediately, with no decision_service restart required."""
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{openfga_api_url}/stores/{store_id}/authorization-models", params={"page_size": 1})
        r.raise_for_status()
        models = r.json().get("authorization_models", [])
        if not models:
            return None
        return models[0]["id"]
    except httpx.HTTPError:
        return None


def check_high_priority_protection(
    action: ActionType,
    parameters: dict,
    evidence: EvidenceResult,
    openfga_api_url: str,
    store_id: str,
    actor_type: str,
    actor_id: str,
    authorization_model_id: str | None = None,
) -> AuthzResult | None:
    """Phase 6 step 0 (docs/adr/0003-protected-high-priority-transfer-authorization.md):
    the SECOND, stricter authorization check for a transfer that mitigates a
    HIGH-priority work order. Returns None when the base authorization
    result already stands (no protection applies, or protection applies and
    ALLOWS it) — callers only need to act when this returns a non-None
    (necessarily DENIED/UNAVAILABLE) result to adopt as the decision's
    final `authz_result`.

    Called only AFTER the base `authorization_relation` check already
    ALLOWED (propose_flow.py) — a base DENY already short-circuits the
    proposal, so this never runs for an actor who couldn't even propose.

    Security review fix: whether protection applies is decided by
    `evidence.route_protected` (a SERVER-SIDE, non-bypassable determination
    of whether the proposed route actually IS a transfer_candidates row for
    a fresh HIGH-priority at-risk work order — see
    `evidence.py::_resolve_route_protection`), never by any caller-declared
    `work_order` parameter. A caller cannot avoid this check by omitting or
    misdeclaring `work_order`; `evidence.py` also fails the whole proposal
    CLOSED (INSUFFICIENT_EVIDENCE, before authorization even runs) whenever
    the route matches a candidate but its priority/at-risk state cannot be
    verified fresh — so this function is only ever reached with a
    confidently-resolved `route_protected` value.
    """
    if not action.protected_relation:
        return None
    if not evidence.route_protected:
        return None
    object_ref = resolve_object(action, parameters, evidence)
    result = check(
        openfga_api_url, store_id, action.protected_relation, object_ref, actor_type, actor_id, authorization_model_id,
    )
    if result.allowed:
        return None
    return result


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
