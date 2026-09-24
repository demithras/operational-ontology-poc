"""Evidence gathering for the baseline variant (Phase 8, spec 10 Variant A).

Reuses THREE things verbatim from the ontology variant, all genuinely
storage-agnostic (no RDF/SPARQL dependency at all):

  - `services.decision_service.evidence.EvidenceResult` — the same dataclass
    (facts_used/facts_excluded/missing/route_protected/...), so
    `services/decision_service/authz.py::check_high_priority_protection`
    (also reused unmodified — see services/baseline/propose_flow.py) works
    identically against either variant's evidence.
  - `gather_expedite_purchase_order_evidence` / `gather_reschedule_work_order_evidence`
    — both are ALREADY pure ERP/MES HTTP reads with zero RDF dependency;
    reusing them means these two action types' evidence gathering is
    LITERALLY the same code for both variants (fairness rule 3: "same
    external source behavior").
  - `services.projection_builder.compute` — the shortage/candidate/current-
    inventory pure functions (dicts in, dicts out; see that module's own
    "no I/O" docstring). Fed here from baseline's own relational tables
    instead of SPARQL results, but the ALGORITHM is identical — a
    deliberate fairness choice (see services/baseline/schema.sql's header
    comment) so this A/B experiment isolates the STORAGE/PROVENANCE
    architecture question (H11), not a second, accidental "whose shortage
    formula is right" question.

Freshness model is genuinely SIMPLER than the ontology variant's, and that
simplicity is itself a real, reportable architectural difference (spec 10
"Metrics: complexity tax"): the ontology variant needs TWO watermarks
(ingestion's per-source watermark AND the hot-projection's own
`computed_at`, because a separate poll/rebuild layer sits between CDC and
the read path — see services/decision_service/evidence.py's own docstring
on the empirical bug that caused). This variant's CDC consumer
(services/baseline/consumer.py) writes STRAIGHT into the queried tables —
there is no second layer to go stale independently of the first — so
freshness only ever needs ONE watermark: `ingestion_watermarks.last_applied_at`
for the owning source system, compared against `now()`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import psycopg
from psycopg.rows import dict_row

from services.decision_service.action_types import ActionType
from services.decision_service.evidence import (
    EvidenceResult,
    gather_expedite_purchase_order_evidence,
    gather_reschedule_work_order_evidence,
)
from services.projection_builder import compute

FRESH = "FRESH"
STALE = "STALE"


def _watermark(conn: psycopg.Connection, system: str) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT last_applied_at FROM ingestion_watermarks WHERE system = %s", (system,))
        row = cur.fetchone()
    return row[0] if row else None


def _freshness_status(conn: psycopg.Connection, system: str, max_age_s: float) -> tuple[str, datetime | None]:
    watermark = _watermark(conn, system)
    if watermark is None:
        return STALE, None
    age_s = (datetime.now(timezone.utc) - watermark).total_seconds()
    return (FRESH, watermark) if age_s <= max_age_s else (STALE, watermark)


def _inventory_available_rows(conn: psycopg.Connection) -> list[dict]:
    """All inventory_lots, in the exact dict shape
    services/projection_builder/compute.py's pure functions expect
    (partUri/whUri/available/lot — plain local-id strings, never real
    URIs; `local_id()` is a no-op on a string with no '/', which every id
    in this domain already satisfies)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT part, warehouse_id, on_hand, reserved, lot_id FROM inventory_lots")
        rows = cur.fetchall()
    return [
        {"partUri": r["part"], "whUri": r["warehouse_id"], "available": r["on_hand"] - r["reserved"], "lot": r["lot_id"]}
        for r in rows
    ]


def _work_order_risk(conn: psycopg.Connection) -> dict[str, compute.WorkOrderRiskRow]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT work_order_id, warehouse_id, status, priority, planned_start FROM work_orders")
        work_orders = [
            {"wo": r["work_order_id"], "whUri": r["warehouse_id"], "status": r["status"],
             "priority": r["priority"], "plannedStart": r["planned_start"] or 0}
            for r in cur.fetchall()
        ]
        cur.execute("SELECT req_id, work_order_id, part, qty FROM bom_requirements")
        requirements = [{"req": r["req_id"], "wo": r["work_order_id"], "partUri": r["part"], "qty": r["qty"]} for r in cur.fetchall()]
        cur.execute(
            """
            SELECT l.line_id, l.po_id, l.part, l.destination_wh, l.qty, p.expected_at, p.status
            FROM purchase_order_lines l JOIN purchase_orders p ON p.po_id = l.po_id
            """
        )
        lines = [
            {"line": r["line_id"], "po": r["po_id"], "partUri": r["part"], "destWhUri": r["destination_wh"],
             "qty": r["qty"], "expectedAt": r["expected_at"] or 0, "status": r["status"]}
            for r in cur.fetchall()
        ]
    inventory_available = _inventory_available_rows(conn)
    return compute.compute_work_order_risk(work_orders, requirements, inventory_available, lines)


def gather_transfer_inventory_evidence(
    conn: psycopg.Connection,
    action: ActionType,
    parameters: dict,
    context: dict,
) -> EvidenceResult:
    result = EvidenceResult()
    part = parameters["part"]
    source_warehouse = parameters["source_warehouse"]
    destination_warehouse = parameters["destination_warehouse"]
    work_order_id = parameters.get("work_order") or context.get("work_order_id")

    max_age_s = float(action.max_evidence_freshness_s)
    src_freshness, verified_through = _freshness_status(conn, "wms", max_age_s)

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM inventory_lots WHERE part = %s AND warehouse_id = %s", (part, source_warehouse))
        src_row = cur.fetchone()

    if src_row is None:
        result.missing.extend(["source_available", "source_quality_status"])
    else:
        available = src_row["on_hand"] - src_row["reserved"]
        result.facts_used["current_source_inventory"] = {
            "available": available,
            "on_hand": src_row["on_hand"],
            "reserved": src_row["reserved"],
            "quality_status": src_row["quality_status"],
            "as_of": src_row["cdc_applied_at"].isoformat(),
            "freshness_status": src_freshness,
            "pipeline_verified_through": verified_through.isoformat() if verified_through else None,
        }
        result.source_positions.append({"system": "wms", "table": "inventory_lots", "pk": src_row["lot_id"], "source_version": src_row["source_version"]})
        result.projection_row_hashes.append(f"{src_row['lot_id']}:{src_row['source_version']}")
        if src_freshness == STALE:
            result.missing.append("source_available_fresh")

    if "destination_exists" in action.closure_required:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM warehouses WHERE warehouse_id = %s", (destination_warehouse,))
            dest_exists = cur.fetchone() is not None
        if not dest_exists:
            result.missing.append("destination_exists")
        else:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT quality_status FROM inventory_lots WHERE part = %s AND warehouse_id = %s", (part, destination_warehouse))
                dest_row = cur.fetchone()
            dest_quality = "OK" if dest_row is None else dest_row["quality_status"]
            result.facts_used["current_destination_compatibility"] = {"exists": True, "quality_status": dest_quality}

    if "safety_stock" in action.closure_required:
        result.facts_used["safety_stock"] = _load_safety_stock(part, source_warehouse, action.policy_package)

    if "reservation_ok" in action.closure_required:
        if src_row is None:
            result.missing.append("reservation_ok")
        else:
            result.facts_used["reservation_ok"] = bool(src_row["on_hand"] >= src_row["reserved"])

    # --- work_order_risk equivalent (compute.py, same algorithm as ontology) ---
    risk = _work_order_risk(conn)
    declared_wo_row = risk.get(work_order_id) if work_order_id else None
    if work_order_id:
        if declared_wo_row is not None:
            result.facts_used["linked_work_order_risk"] = {
                "warehouse": declared_wo_row.warehouse,
                "shortage": declared_wo_row.shortage,
                "at_risk": declared_wo_row.at_risk,
                "severity": declared_wo_row.severity,
                "priority": declared_wo_row.priority,
            }
        else:
            result.facts_excluded["linked_work_order_risk"] = {"work_order_id": work_order_id, "reason": "no_open_risk_row"}

    # --- Route protection (docs/adr/0003) — SAME algorithm, computed live ---
    inventory_available = _inventory_available_rows(conn)
    candidates = compute.compute_transfer_candidates(risk, inventory_available)
    matching = [c for c in candidates if c.part == part and c.source_warehouse == source_warehouse and c.destination_warehouse == destination_warehouse]
    if not matching:
        route_status, protecting = "NOT_APPLICABLE", []
    else:
        mes_freshness, _ = _freshness_status(conn, "mes", max_age_s)
        if mes_freshness == STALE:
            route_status, protecting = "UNRESOLVED", []
        else:
            protecting = [c.work_order_id for c in matching if risk[c.work_order_id].priority == "HIGH" and risk[c.work_order_id].at_risk]
            route_status = "PROTECTED" if protecting else "UNPROTECTED"
    result.facts_used["route_protection"] = {"status": route_status, "work_order_ids": protecting}
    if route_status == "UNRESOLVED":
        result.missing.append("route_protection_fresh")
    if declared_wo_row is not None and declared_wo_row.at_risk and work_order_id not in protecting:
        result.missing.append("work_order_route_mismatch")

    result.observed_at = datetime.now(timezone.utc)
    return result


def _load_safety_stock(part: str, warehouse: str, policy_package: str) -> int:
    """Same source of truth as the ontology variant
    (contracts/policies/v1|v2/data.json — a SHARED contract file, fairness
    rule 4) and the identical lookup logic
    (services/decision_service/evidence.py::_load_safety_stock)."""
    from services.decision_service.evidence import _load_safety_stock as _shared_load_safety_stock

    return _shared_load_safety_stock(part, warehouse, policy_package)


def gather_evidence(
    action: ActionType,
    parameters: dict,
    context: dict,
    conn: psycopg.Connection,
    http_clients: dict[str, httpx.Client],
) -> EvidenceResult:
    if action.name == "transfer_inventory":
        return gather_transfer_inventory_evidence(conn, action, parameters, context)
    if action.name == "expedite_purchase_order":
        return gather_expedite_purchase_order_evidence(http_clients, action, parameters, context)
    if action.name == "reschedule_work_order":
        return gather_reschedule_work_order_evidence(http_clients, action, parameters, context)
    raise ValueError(f"no evidence gatherer registered for action type {action.name!r}")
