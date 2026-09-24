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
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import psycopg

from services.projection_builder import freshness, reader
from services.decision_service.action_types import ActionType
from services.common.sparql_escape import escape_sparql_literal

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_DATA_PATH = REPO_ROOT / "contracts" / "policies" / "v1" / "data.json"

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


def _load_safety_stock(part: str, warehouse: str) -> int:
    data = json.loads(POLICY_DATA_PATH.read_text())
    per_part = data.get("safety_stock", {}).get(part, {})
    if warehouse in per_part:
        return int(per_part[warehouse])
    return int(data.get("default_safety_stock", 0))


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
    action: ActionType,
    parameters: dict,
    context: dict,
) -> EvidenceResult:
    result = EvidenceResult()
    part = parameters["part"]
    source_warehouse = parameters["source_warehouse"]
    destination_warehouse = parameters["destination_warehouse"]
    work_order_id = context.get("work_order_id")

    observed_ats: list[datetime] = []

    src_row = reader.get_current_inventory(conn, part, source_warehouse)
    if src_row is None:
        result.missing.extend(["source_available", "source_quality_status"])
    else:
        src_freshness = freshness.evaluate(src_row["as_of"], max_age_s=int(action.max_evidence_freshness_s))
        result.facts_used["current_source_inventory"] = {
            "available": src_row["available"],
            "on_hand": src_row["on_hand"],
            "reserved": src_row["reserved"],
            "quality_status": src_row["quality_status"],
            "as_of": src_row["as_of"].isoformat(),
            "freshness_status": src_freshness,
        }
        result.source_positions.extend(src_row["source_positions"])
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
        result.facts_used["safety_stock"] = _load_safety_stock(part, source_warehouse)

    if work_order_id:
        wo_row = reader.get_work_order_risk(conn, work_order_id)
        if wo_row is not None:
            result.facts_used["linked_work_order_risk"] = {
                "warehouse": wo_row["warehouse"],
                "shortage": wo_row["shortage"],
                "at_risk": wo_row["at_risk"],
                "severity": wo_row["severity"],
            }
            result.source_positions.extend(wo_row["source_positions"])
            result.projection_row_hashes.append(wo_row["content_hash"])
            observed_ats.append(wo_row["as_of"])
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

    result.observed_at = max(observed_ats) if observed_ats else datetime.now(timezone.utc)
    return result


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
        return gather_transfer_inventory_evidence(conn, rdf4j_client, action, parameters, context)
    if action.name == "expedite_purchase_order":
        return gather_expedite_purchase_order_evidence(http_clients, action, parameters, context)
    if action.name == "reschedule_work_order":
        return gather_reschedule_work_order_evidence(http_clients, action, parameters, context)
    raise ValueError(f"no evidence gatherer registered for action type {action.name!r}")
