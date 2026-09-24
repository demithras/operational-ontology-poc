"""Evidence gathering + closed-world closure check — docs/experiment/spec/
05_ontology_and_contracts.md "Closed-world islands" / H14: "every action
type declares its required evidence and closure assumptions ... missing
required evidence causes INSUFFICIENT_EVIDENCE, not a guessed false/true
result."

Reads ONLY from the hot projections (services.projection_builder.reader,
the same tables Phase 4 built, never a second parallel query path) and the
semantic core (RDF4J, for existence checks the hot projections don't cover)
plus contracts/policies/v1/data.json (the safety_stock source of truth,
shared with the OPA bundle it is versioned alongside — see that file's
header comment). transfer_inventory gets full evidence gathering; the other
two action types use a lighter ERP/MES REST read (documented scoping
decision, see docs/experiment/implementation-notes.md Phase 5 section).

Phase 5 fix — watermark-based evidence freshness (docs/experiment/spec/
04_architecture.md consistency model; docs/experiment/implementation-notes.md
Phase 5 fix section has the full empirical write-up): freshness does NOT
mean "how long ago did this fact's own row last change" — it means "how
recently did we VERIFY our view is current against the source", which stays
TRUE even when nothing has changed for minutes, as long as the CDC pipeline
is alive and draining. The original implementation fed `row["as_of"]` (the
row's own last-changed timestamp, from `oo:SourcePosition`) into
`freshness.evaluate()`, which made ANY untouched-for-5s lot permanently
"STALE" even on a perfectly healthy, fully-caught-up system — the canonical
incident could never pass on a quiet stack. `_resolve_source_inventory_with_freshness`
replaces that with `min(ingestion's per-source watermark, the row's own
`computed_at`)`: the watermark (services/ingestion/consumer.py, driven by
Debezium heartbeats AND real CDC events) proves ingestion has drained the
source's Kafka topics up through wall-clock time T; `computed_at` (already
written by services/projection_builder on every rebuild cycle, Phase 4)
proves the hot projection itself was rebuilt at or after that point. Both
must be recent for the read to be trustworthy — either one going stale
(a stopped connector, or a stopped projection_builder) independently
produces STALE, matching F26's "pause the connector / stop the builder /
freeze the watermark" list of equivalent staleness injections.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg

from services.projection_builder import freshness, reader
from services.decision_service.action_types import ActionType
from services.common.sparql_escape import escape_sparql_literal

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICIES_ROOT = REPO_ROOT / "contracts" / "policies"
# Backward-compatible constant (unused internally after Phase 7 — kept for
# any external reference); _load_safety_stock now resolves the version-
# specific path itself.
POLICY_DATA_PATH = POLICIES_ROOT / "v1" / "data.json"

FAC_PREFIX = "PREFIX fac: <https://example.local/factory/>"


@dataclass
class EvidenceResult:
    facts_used: dict = field(default_factory=dict)
    facts_excluded: dict = field(default_factory=dict)
    source_positions: list[dict] = field(default_factory=list)
    projection_row_hashes: list[str] = field(default_factory=list)
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    missing: list[str] = field(default_factory=list)

    @property
    def sufficient(self) -> bool:
        return not self.missing

    @property
    def route_protection_status(self) -> str:
        """Phase 6 step 0 security fix (docs/adr/0003-protected-high-priority-transfer-authorization.md):
        one of NOT_APPLICABLE (this route is not a transfer_candidates row
        for any work order) | UNPROTECTED (it is, but not a fresh HIGH+
        at-risk one) | PROTECTED (it is a fresh HIGH-priority, at-risk
        candidate) | UNRESOLVED (matched a candidate but freshness/priority
        could not be confidently determined — closure.py FAILS CLOSED on
        this, see gather_transfer_inventory_evidence)."""
        return (self.facts_used.get("route_protection") or {}).get("status", "NOT_APPLICABLE")

    @property
    def route_protecting_work_orders(self) -> list[str]:
        return (self.facts_used.get("route_protection") or {}).get("work_order_ids", [])

    @property
    def route_protected(self) -> bool:
        return self.route_protection_status == "PROTECTED"


def _load_safety_stock(part: str, warehouse: str, action_version_dir: str = "v1") -> int:
    """Phase 7 V2 'changed safety-stock policy': V2+ reads
    contracts/policies/v2/data.json's `safety_stock_v2`/`default_safety_stock_v2`
    keys instead of v1's `safety_stock`/`default_safety_stock` — a
    genuinely different (higher) number for the same (part, warehouse), see
    that file's header comment. `action_version_dir` is the ActionType's OWN
    contract directory (services/decision_service/action_types.py's
    `version_dir`), never the global deployed_version pointer directly —
    this function must use whatever version the CALLING action was actually
    loaded from, so a historical V1 evaluation (replay) never accidentally
    reads V2 numbers."""
    key = "safety_stock" if action_version_dir == "v1" else "safety_stock_v2"
    default_key = "default_safety_stock" if action_version_dir == "v1" else "default_safety_stock_v2"
    data_path = POLICIES_ROOT / action_version_dir / "data.json"
    data = json.loads(data_path.read_text())
    per_part = data.get(key, {}).get(part, {})
    if warehouse in per_part:
        return int(per_part[warehouse])
    return int(data.get(default_key, 0))


def _fetch_ingestion_watermark(http_clients: dict[str, httpx.Client], system: str) -> datetime | None:
    """The wall-clock time services/ingestion last successfully processed
    EITHER a real CDC event OR a Debezium heartbeat message for `system`
    (services/ingestion/health.py::HealthState.watermarks). Returns None if
    ingestion is unreachable or has not yet recorded a watermark for that
    system (e.g. right after a fresh restart, before its first heartbeat) —
    callers must treat None as "cannot prove freshness", never as "assume
    fresh"."""
    try:
        resp = http_clients["ingestion"].get("/health")
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    watermark_iso = resp.json().get("watermarks", {}).get(system)
    if watermark_iso is None:
        return None
    return datetime.fromisoformat(watermark_iso)


# Sized from an empirical measurement, not guessed: running
# tests/integration/test_cdc_ingestion.py's OWN (pre-existing, Phase 3)
# RDF4J-outage test showed services/projection_builder's build cycle itself
# failing (DNS/connection error reaching the stopped RDF4J) with one
# observed failed-build duration of ~4s, plus its own ~3s poll interval
# before the NEXT (successful) cycle updates `computed_at` again — up to
# ~7s of incidental staleness from an ENTIRELY UNRELATED test elsewhere in
# the same `make test` run, not from any problem in this decision. 10
# attempts * 0.8s = 8s covers that measured worst case with margin, while
# still returning immediately (no added latency at all) the moment either
# side catches up — which is every request except the rare one that races
# an incidental outage test.
_FRESHNESS_RETRY_ATTEMPTS = 10
_FRESHNESS_RETRY_DELAY_S = 0.8


def _resolve_source_inventory_with_freshness(
    conn: psycopg.Connection,
    http_clients: dict[str, httpx.Client],
    part: str,
    warehouse: str,
    max_age_s: float,
) -> tuple[dict | None, str, datetime | None]:
    """Returns (row, freshness_status, verified_through). Re-reads BOTH the
    hot-projection row (for a fresh `computed_at`) AND the ingestion
    watermark on EACH attempt — not just the watermark — because either one
    can independently lag: `computed_at` only advances when
    services/projection_builder's own poll loop runs, and that loop shares
    the same host CPU as everything else in this docker-compose stack.

    Retrying is deliberately NOT a way to widen `max_age_s` — a genuinely
    SUSTAINED stall (F26 stops services/projection_builder for the whole
    duration of the propose() call, not just for a moment) still exhausts
    every attempt and correctly ends up STALE, verified by
    tests/integration/test_decision_service_dependency_outage.py's own F26
    test. This retry window is defense-in-depth, not the primary fix for
    the real bug it was originally added for: a full `make test` run showed
    the ROOT CAUSE was that tests which stop/restart RDF4J or
    projection_builder (Phase 3's own RDF4J-outage test, and this phase's
    F22/F26) were returning control to the next test the moment the
    disrupted service's bare HTTP health check responded again — several
    seconds BEFORE ingestion resumed heartbeats or projection_builder
    completed its first post-restart rebuild, leaking an 11-19s stale
    window into whatever ran next. That is fixed at the SOURCE
    (`services/ingestion/readiness.py::wait_for_fresh_hot_projection`,
    called from every such test's own `finally` block — see
    docs/experiment/implementation-notes.md's Phase 5 fix section for the
    full empirical write-up). This retry window remains as a second,
    independent safety margin for any future test or real operational
    hiccup that disrupts the pipeline without yet knowing to wait for full
    reconvergence — it costs nothing on the happy path (returns immediately
    the moment both signals are fresh) and only adds latency in that
    already-unhappy case."""
    row: dict | None = None
    verified_through: datetime | None = None
    for attempt in range(_FRESHNESS_RETRY_ATTEMPTS):
        row = reader.get_current_inventory(conn, part, warehouse)
        if row is None:
            return None, freshness.STALE, None  # no row at all — retrying can't help this
        watermark = _fetch_ingestion_watermark(http_clients, "wms")
        if watermark is not None:
            verified_through = min(watermark, row["computed_at"])
            if freshness.evaluate(verified_through, max_age_s=max_age_s) == freshness.FRESH:
                return row, freshness.FRESH, verified_through
        else:
            verified_through = None
        if attempt < _FRESHNESS_RETRY_ATTEMPTS - 1:
            # F21 deadlock, found empirically while building
            # tests/faults/test_cdc_delay_and_kafka_outage.py: this whole
            # function runs on the SAME connection/transaction propose()'s
            # caller passed in (services/decision_service/app.py's one
            # `with get_conn() as conn:` per request, autocommit=False —
            # services/common/db.py), so a SUSTAINED-stale run (Kafka down
            # for the whole request, not just one poll gap — exactly F21)
            # held the `current_inventory` read's AccessShareLock for the
            # ENTIRE up-to-8s retry window, INSTEAD OF releasing it between
            # polls. services/projection_builder's own TRUNCATE order
            # (work_order_risk -> transfer_candidates -> current_inventory
            # -> action_eligibility_summary, one transaction per ~3s poll
            # cycle) then reliably queued up behind that lock, and this
            # request's LATER read (services/decision_service/evidence.py::
            # _resolve_route_protection's transfer_candidates/work_order_risk
            # JOIN, later in the SAME transaction) reliably completed the
            # AB-BA cycle against it — turning the documented-as-rare Phase 6
            # deadlock window (implementation-notes.md, "verified with 5
            # consecutive clean runs") into a NEAR-CERTAIN one under any
            # sustained staleness. This read-only function has nothing
            # pending to lose by committing between polls (propose()'s first
            # WRITE is store.insert_decision's own commit, at the very end
            # of the whole request) — releasing the lock here lets
            # projection_builder's cycle interleave normally instead of
            # queuing up behind an 8-second-long read transaction.
            conn.commit()
            time.sleep(_FRESHNESS_RETRY_DELAY_S)
    return row, freshness.STALE, verified_through


def _warehouse_exists(rdf4j_client, warehouse_id: str) -> bool:
    # F31 defense-in-depth: services/decision_service/schemas.py's
    # `_ID_PATTERN` already rejects any warehouse_id containing characters
    # that could break out of this literal (F01, HTTP 422, before this
    # function is ever reached) — this escape is the SECOND layer, not the
    # only one. See services/common/sparql_escape.py's module docstring.
    safe_id = escape_sparql_literal(warehouse_id)
    query = f'{FAC_PREFIX} ASK {{ ?w a fac:Warehouse ; fac:warehouseId "{safe_id}" }}'
    return rdf4j_client.ask(query)


def gather_transfer_inventory_evidence(
    conn: psycopg.Connection,
    rdf4j_client,
    http_clients: dict[str, httpx.Client],
    action: ActionType,
    parameters: dict,
    context: dict,
) -> EvidenceResult:
    result = EvidenceResult()
    part = parameters["part"]
    source_warehouse = parameters["source_warehouse"]
    destination_warehouse = parameters["destination_warehouse"]
    # Phase 6 step 0: `parameters.work_order` is the canonical, hash-covered
    # path (see contracts/actions/v1/transfer_inventory.yaml); the older
    # `context.work_order_id` is still accepted for backward compatibility
    # but is informational-only (never hash-covered, never authorization-
    # relevant — see docs/adr/0003-protected-high-priority-transfer-authorization.md).
    work_order_id = parameters.get("work_order") or context.get("work_order_id")

    observed_ats: list[datetime] = []

    # WMS owns InventoryLot (docs/experiment/implementation-notes.md
    # Phase 3 "Source-of-truth hierarchy") — the relevant watermark is
    # ingestion's "wms" watermark, not the row's own `as_of`. Re-reads BOTH
    # the row and the watermark across its own short retry window (see its
    # docstring) rather than a single point-in-time snapshot.
    src_row, src_freshness, verified_through = _resolve_source_inventory_with_freshness(
        conn, http_clients, part, source_warehouse, max_age_s=float(action.max_evidence_freshness_s)
    )
    if src_row is None:
        result.missing.extend(["source_available", "source_quality_status"])
    else:
        result.facts_used["current_source_inventory"] = {
            "available": src_row["available"],
            "on_hand": src_row["on_hand"],
            "reserved": src_row["reserved"],
            "quality_status": src_row["quality_status"],
            "as_of": src_row["as_of"].isoformat(),
            "freshness_status": src_freshness,
            "pipeline_verified_through": verified_through.isoformat() if verified_through else None,
        }
        result.source_positions.extend(src_row["source_positions"])
        # The per-source pipeline watermark itself, recorded alongside the
        # per-entity source_positions this action's evidence used (spec 04
        # "Evidence snapshot" hybrid manifest; this Phase 5 fix's own
        # requirement to make the watermark queryable/replayable, not just
        # used in-memory for the gate decision).
        result.source_positions.append({
            "system": "wms",
            "kind": "watermark",
            "verified_through": verified_through.isoformat() if verified_through else None,
        })
        result.projection_row_hashes.append(src_row["content_hash"])
        observed_ats.append(src_row["as_of"])
        if src_freshness == freshness.STALE:
            result.missing.append("source_available_fresh")

    if "destination_exists" in action.closure_required:
        dest_exists = _warehouse_exists(rdf4j_client, destination_warehouse)
        if not dest_exists:
            result.missing.append("destination_exists")
        else:
            dest_row = reader.get_current_inventory(conn, part, destination_warehouse)
            dest_quality = "OK" if dest_row is None else dest_row["quality_status"]
            result.facts_used["current_destination_compatibility"] = {
                "exists": True,
                "quality_status": dest_quality,
            }
            if dest_row is not None:
                result.source_positions.extend(dest_row["source_positions"])
                result.projection_row_hashes.append(dest_row["content_hash"])
                observed_ats.append(dest_row["as_of"])

    if "safety_stock" in action.closure_required:
        result.facts_used["safety_stock"] = _load_safety_stock(part, source_warehouse, action.version_dir)

    # Phase 7 V2 'new required evidence field': reservation_ok (V2+ only —
    # contracts/actions/v2/transfer_inventory.yaml's closure.required).
    # Always resolvable once src_row exists (both on_hand and reserved are
    # already part of every current_inventory row, V1 and V2 alike); only
    # ever missing when src_row itself couldn't be resolved (already
    # recorded as source_available/source_quality_status above).
    if "reservation_ok" in action.closure_required:
        if src_row is None:
            result.missing.append("reservation_ok")
        else:
            result.facts_used["reservation_ok"] = bool(src_row["on_hand"] >= src_row["reserved"])

    declared_wo_row = None
    if work_order_id:
        declared_wo_row = reader.get_work_order_risk(conn, work_order_id)
        # Phase 6 step 0 security fix: `priority` (LOW|MEDIUM|HIGH) now comes
        # straight from the work_order_risk HOT PROJECTION (see
        # contracts/projections/v1/work_order_risk.yaml — fac:priority passed
        # through unchanged), not a live MES call. This fact is purely
        # INFORMATIONAL/explanatory (H13 "which evidence was used") — it is
        # NEVER what gates the protected-transfer authorization check below;
        # see `route_protection` for the actual (non-bypassable) signal.
        if declared_wo_row is not None:
            result.facts_used["linked_work_order_risk"] = {
                "warehouse": declared_wo_row["warehouse"],
                "shortage": declared_wo_row["shortage"],
                "at_risk": declared_wo_row["at_risk"],
                "severity": declared_wo_row["severity"],
                "priority": declared_wo_row["priority"],
            }
            result.source_positions.extend(declared_wo_row["source_positions"])
            result.projection_row_hashes.append(declared_wo_row["content_hash"])
            observed_ats.append(declared_wo_row["as_of"])
        # A work_order_id that resolves to nothing (terminal/unknown work
        # order) is recorded as an EXCLUDED candidate, not a closure
        # failure — linked_work_order_risk is informational context, not a
        # hard-required field (see contracts/actions/v1/transfer_inventory.yaml
        # closure.required, which deliberately omits it).
        else:
            result.facts_excluded["linked_work_order_risk"] = {"work_order_id": work_order_id, "reason": "no_open_risk_row"}

    # Candidate evidence gathered but not part of THIS action's
    # evidence_requirements — H13 forensic query 3 ("which evidence was
    # available but excluded"). transfer_candidates rows for the same part/
    # work order are the clearest example: descriptive-only per Phase 4
    # (R3), never consulted by this gate, but visibly available at proposal
    # time.
    if work_order_id:
        candidates = reader.get_transfer_candidates(conn, work_order_id)
        if candidates:
            result.facts_excluded["other_transfer_candidates"] = [
                {"candidate_id": c["candidate_id"], "source_warehouse": c["source_warehouse"], "candidate_quantity": c["candidate_quantity"]}
                for c in candidates
                if c["source_warehouse"] != source_warehouse
            ]

    # --- Phase 6 step 0 security fix: server-side, non-bypassable
    # high-priority-mitigation detection (docs/adr/0003-protected-high-priority-transfer-authorization.md).
    # Computed from what the proposed (part, source_warehouse,
    # destination_warehouse) route ACTUALLY IS a transfer_candidates row
    # for — a caller CANNOT avoid the protected-authorization check merely
    # by omitting (or misdeclaring) `work_order`/`context.work_order_id`.
    route_status, route_work_order_ids = _resolve_route_protection(
        conn, http_clients, part, source_warehouse, destination_warehouse,
        max_age_s=float(action.max_evidence_freshness_s),
    )
    result.facts_used["route_protection"] = {"status": route_status, "work_order_ids": route_work_order_ids}
    if route_status == "UNRESOLVED":
        # Fails CLOSED for EVERY actor, not just when a work_order was
        # declared: the route demonstrably matches an at-risk work order's
        # transfer_candidates row, but we cannot currently prove (fresh
        # MES-derived priority + at-risk state) whether that work order is
        # HIGH priority — a caller cannot be authorized against a check we
        # cannot evaluate. INSUFFICIENT_EVIDENCE, never a silent allow.
        result.missing.append("route_protection_fresh")
    if declared_wo_row is not None and declared_wo_row["at_risk"] and work_order_id not in route_work_order_ids:
        # Honesty check (security review): the caller explicitly claimed a
        # real, currently at-risk work order as this transfer's mitigation
        # target, but the route it actually proposed (this exact part/
        # source/destination triple) is not a real transfer_candidates row
        # for THAT work order (whether or not it happens to match a
        # DIFFERENT one) — the declaration and the proposal disagree.
        result.missing.append("work_order_route_mismatch")

    result.observed_at = max(observed_ats) if observed_ats else datetime.now(timezone.utc)
    return result


def _resolve_route_protection(
    conn: psycopg.Connection,
    http_clients: dict[str, httpx.Client],
    part: str,
    source_warehouse: str,
    destination_warehouse: str,
    max_age_s: float,
) -> tuple[str, list[str]]:
    """Returns (status, protecting_work_order_ids).

    status is one of:
      NOT_APPLICABLE — this (part, source_warehouse, destination_warehouse)
        is not a transfer_candidates row for any work order at all (the
        overwhelming majority of ordinary, unprotected transfers).
      UNRESOLVED — it IS a candidate for at least one work order, but that
        work order's priority/at-risk state could not be verified FRESH
        (min(MES ingestion watermark, the work_order_risk row's own
        `computed_at`) — same watermark pattern as
        `_resolve_source_inventory_with_freshness` above, scoped to the one
        source system `fac:priority` is authoritative for). Callers MUST
        treat this as fail-closed.
      UNPROTECTED — resolved fresh, but none of the matching work orders are
        both HIGH priority and currently at_risk.
      PROTECTED — resolved fresh and at least one matching work order is
        HIGH priority and at_risk; `protecting_work_order_ids` names them.
    """
    # ONE JOINed query (not two separate round trips) — see
    # get_transfer_candidates_with_risk_for_route's own docstring: found
    # empirically necessary to close a real AB-BA deadlock window against
    # services/projection_builder's TRUNCATE order.
    candidates = reader.get_transfer_candidates_with_risk_for_route(conn, part, source_warehouse, destination_warehouse)
    if not candidates:
        return "NOT_APPLICABLE", []

    mes_watermark = _fetch_ingestion_watermark(http_clients, "mes")
    protecting: list[str] = []
    seen_work_orders: set[str] = set()
    for candidate in candidates:
        wo_id = candidate["work_order_id"]
        if wo_id in seen_work_orders:
            continue
        seen_work_orders.add(wo_id)
        if candidate["priority"] is None:
            return "UNRESOLVED", []
        verified_through = min(mes_watermark, candidate["risk_computed_at"]) if mes_watermark is not None else None
        if verified_through is None or freshness.evaluate(verified_through, max_age_s=max_age_s) == freshness.STALE:
            return "UNRESOLVED", []
        if candidate["priority"] == "HIGH" and candidate["at_risk"]:
            protecting.append(wo_id)
    return ("PROTECTED", protecting) if protecting else ("UNPROTECTED", [])


def gather_expedite_purchase_order_evidence(
    http_clients: dict[str, httpx.Client],
    action: ActionType,
    parameters: dict,
    context: dict,
) -> EvidenceResult:
    result = EvidenceResult()
    po_id = parameters["po_id"]
    resp = http_clients["erp"].get(f"/purchase_orders/{po_id}")
    if resp.status_code != 200:
        result.missing.append("po_status")
        return result
    po = resp.json()
    # A PO's lines may in principle target different warehouses; this POC
    # binds authorization to the FIRST line's destination only (documented
    # simplification — see services/decision_service/authz.py::resolve_object).
    destination_warehouse = po["lines"][0]["destination_warehouse"] if po.get("lines") else None
    result.facts_used["current_po_status"] = {"po_status": po["status"], "destination_warehouse": destination_warehouse}
    result.observed_at = datetime.now(timezone.utc)
    return result


def gather_reschedule_work_order_evidence(
    http_clients: dict[str, httpx.Client],
    action: ActionType,
    parameters: dict,
    context: dict,
) -> EvidenceResult:
    result = EvidenceResult()
    work_order_id = parameters["work_order_id"]
    resp = http_clients["mes"].get(f"/work_orders/{work_order_id}")
    if resp.status_code != 200:
        result.missing.extend(["work_order_status", "priority"])
        return result
    wo = resp.json()
    result.facts_used["current_work_order_status"] = {
        "work_order_status": wo["status"],
        "priority": wo["priority"],
        "warehouse": wo["warehouse"],
    }
    result.observed_at = datetime.now(timezone.utc)
    return result


def gather_evidence(
    action: ActionType,
    parameters: dict,
    context: dict,
    conn: psycopg.Connection,
    rdf4j_client,
    http_clients: dict[str, httpx.Client],
) -> EvidenceResult:
    if action.name == "transfer_inventory":
        return gather_transfer_inventory_evidence(conn, rdf4j_client, http_clients, action, parameters, context)
    if action.name == "expedite_purchase_order":
        return gather_expedite_purchase_order_evidence(http_clients, action, parameters, context)
    if action.name == "reschedule_work_order":
        return gather_reschedule_work_order_evidence(http_clients, action, parameters, context)
    raise ValueError(f"no evidence gatherer registered for action type {action.name!r}")
