"""Pure computation over RDF-sourced raw facts (services/projection_builder/
rdf_reader.py output) -> projection rows. No I/O in this module — everything
here is plain functions over dicts/lists so it is trivially unit-testable
and so the "differential projection test"
(tests/integration/test_projection_differential.py) is comparing two
genuinely independent implementations of the same shortage/at_risk formula:
this one (SPARQL-sourced raw facts, hand-written aggregation) and
reference_model/derive.py (pure WorldState objects) — never the same
function called twice.

Algorithm mirrors reference_model/derive.py's shortage formula exactly
(see docs/experiment/spec/03_domain_scenario.md's canonical incident):

    shortage = sum over each required part of
        max(0, required_qty - available_at(part, wo.warehouse)
                            - incoming_before(part, wo.warehouse, wo.planned_start))
    at_risk = shortage > 0
"""

from __future__ import annotations

from dataclasses import dataclass

from services.projection_builder.rdf_reader import local_id

TERMINAL_WO_STATUSES = frozenset({"DONE", "CANCELLED"})
EXCLUDED_PO_STATUSES = frozenset({"RECEIVED", "CANCELLED"})


@dataclass(frozen=True)
class EntityRef:
    class_name: str
    local_id: str


@dataclass(frozen=True)
class WorkOrderRiskRow:
    work_order_id: str
    warehouse: str
    shortage: int
    at_risk: bool
    severity: str  # CRITICAL | MITIGATED
    priority: str  # LOW | MEDIUM | HIGH — fac:priority passed through unchanged (Phase 6 step 0)
    part_shortfalls: tuple[tuple[str, int], ...]  # (part_local_id, shortfall) — internal, feeds transfer_candidates
    contributing_entities: tuple[EntityRef, ...]


@dataclass(frozen=True)
class TransferCandidateRow:
    candidate_id: str
    work_order_id: str
    part: str
    destination_warehouse: str
    source_warehouse: str
    candidate_quantity: int
    available_at_source: int
    contributing_entities: tuple[EntityRef, ...]


@dataclass(frozen=True)
class CurrentInventoryRow:
    part: str
    warehouse: str
    on_hand: int
    reserved: int
    available: int
    quality_status: str
    contributing_entities: tuple[EntityRef, ...]


@dataclass(frozen=True)
class ActionEligibilitySummaryRow:
    work_order_id: str
    at_risk: bool
    shortage: int
    severity: str
    transfer_candidate_count: int
    max_single_candidate_quantity: int
    total_candidate_quantity: int
    mitigation_feasible: bool


def compute_work_order_risk(
    work_orders: list[dict],
    requirements: list[dict],
    inventory_available: list[dict],
    incoming_purchase_lines: list[dict],
) -> dict[str, WorkOrderRiskRow]:
    inv_index: dict[tuple[str, str], tuple[int, str]] = {}
    for row in inventory_available:
        key = (local_id(row["partUri"]), local_id(row["whUri"]))
        inv_index[key] = (int(row["available"]), local_id(row["lot"]))

    reqs_by_wo: dict[str, list[dict]] = {}
    for row in requirements:
        reqs_by_wo.setdefault(local_id(row["wo"]), []).append(row)

    lines_by_part_wh: dict[tuple[str, str], list[dict]] = {}
    for row in incoming_purchase_lines:
        key = (local_id(row["partUri"]), local_id(row["destWhUri"]))
        lines_by_part_wh.setdefault(key, []).append(row)

    result: dict[str, WorkOrderRiskRow] = {}
    for wo_row in work_orders:
        if wo_row["status"] in TERMINAL_WO_STATUSES:
            continue
        wo_local = local_id(wo_row["wo"])
        warehouse = local_id(wo_row["whUri"])
        planned_start = int(wo_row["plannedStart"])

        shortage = 0
        part_shortfalls: list[tuple[str, int]] = []
        contributing: list[EntityRef] = [EntityRef("WorkOrder", wo_local)]

        # Group requirement rows by PART first (MES's bom_requirements table
        # has no UNIQUE(work_order_id, part_id) constraint, so a work order
        # can legitimately carry more than one requirement ROW for the same
        # part — found empirically in the SEED=42 generated dataset, not
        # just a theoretical edge case). Summing required_qty across those
        # rows before computing shortage matches reference_model.derive()'s
        # semantics (its WorkOrder.requirements is a part -> qty MAPPING, one
        # entry per part) and avoids evaluating the SAME available/incoming
        # supply independently per duplicate row, which would double-count
        # it and also produce duplicate transfer_candidates rows for the
        # same (work_order, part, source_warehouse) key.
        required_by_part: dict[str, int] = {}
        for req_row in reqs_by_wo.get(wo_local, []):
            part_local = local_id(req_row["partUri"])
            required_by_part[part_local] = required_by_part.get(part_local, 0) + int(req_row["qty"])
            contributing.append(EntityRef("BomRequirement", local_id(req_row["req"])))

        for part_local, required_qty in required_by_part.items():
            available, lot_local = inv_index.get((part_local, warehouse), (0, None))
            if lot_local is not None:
                contributing.append(EntityRef("InventoryLot", lot_local))

            incoming = 0
            for line_row in lines_by_part_wh.get((part_local, warehouse), []):
                if line_row["status"] in EXCLUDED_PO_STATUSES:
                    continue
                if int(line_row["expectedAt"]) > planned_start:
                    continue
                incoming += int(line_row["qty"])
                contributing.append(EntityRef("PurchaseOrder", local_id(line_row["po"])))
                contributing.append(EntityRef("PurchaseOrderLine", local_id(line_row["line"])))

            part_shortage = max(0, required_qty - available - incoming)
            shortage += part_shortage
            if part_shortage > 0:
                part_shortfalls.append((part_local, part_shortage))

        at_risk = shortage > 0
        result[wo_local] = WorkOrderRiskRow(
            work_order_id=wo_local,
            warehouse=warehouse,
            shortage=shortage,
            at_risk=at_risk,
            severity="CRITICAL" if at_risk else "MITIGATED",
            priority=wo_row["priority"],
            part_shortfalls=tuple(part_shortfalls),
            contributing_entities=tuple(contributing),
        )
    return result


def compute_transfer_candidates(
    work_order_risk: dict[str, WorkOrderRiskRow],
    inventory_available: list[dict],
) -> list[TransferCandidateRow]:
    inv_by_part: dict[str, list[tuple[str, int, str]]] = {}
    for row in inventory_available:
        part_local = local_id(row["partUri"])
        wh_local = local_id(row["whUri"])
        inv_by_part.setdefault(part_local, []).append((wh_local, int(row["available"]), local_id(row["lot"])))

    candidates: list[TransferCandidateRow] = []
    for wo_row in work_order_risk.values():
        if not wo_row.at_risk:
            continue
        for part_local, shortfall in wo_row.part_shortfalls:
            for wh_local, available, lot_local in inv_by_part.get(part_local, []):
                if wh_local == wo_row.warehouse or available <= 0:
                    continue
                candidates.append(
                    TransferCandidateRow(
                        candidate_id=f"{wo_row.work_order_id}|{part_local}|{wh_local}",
                        work_order_id=wo_row.work_order_id,
                        part=part_local,
                        destination_warehouse=wo_row.warehouse,
                        source_warehouse=wh_local,
                        candidate_quantity=min(available, shortfall),
                        available_at_source=available,
                        contributing_entities=(EntityRef("InventoryLot", lot_local),),
                    )
                )
    return candidates


def compute_current_inventory(inventory_lots: list[dict]) -> list[CurrentInventoryRow]:
    return [
        CurrentInventoryRow(
            part=local_id(row["partUri"]),
            warehouse=local_id(row["whUri"]),
            on_hand=int(row["onHand"]),
            reserved=int(row["reserved"]),
            available=int(row["available"]),
            quality_status=row["qualityStatus"],
            contributing_entities=(EntityRef("InventoryLot", local_id(row["lot"])),),
        )
        for row in inventory_lots
    ]


def compute_action_eligibility_summary(
    work_order_risk: dict[str, WorkOrderRiskRow],
    transfer_candidates: list[TransferCandidateRow],
) -> dict[str, ActionEligibilitySummaryRow]:
    candidates_by_wo: dict[str, list[TransferCandidateRow]] = {}
    for c in transfer_candidates:
        candidates_by_wo.setdefault(c.work_order_id, []).append(c)

    result: dict[str, ActionEligibilitySummaryRow] = {}
    for wo_id, risk in work_order_risk.items():
        cands = candidates_by_wo.get(wo_id, [])
        total_qty = sum(c.candidate_quantity for c in cands)
        result[wo_id] = ActionEligibilitySummaryRow(
            work_order_id=wo_id,
            at_risk=risk.at_risk,
            shortage=risk.shortage,
            severity=risk.severity,
            transfer_candidate_count=len(cands),
            max_single_candidate_quantity=max((c.candidate_quantity for c in cands), default=0),
            total_candidate_quantity=total_qty,
            mitigation_feasible=(not risk.at_risk) or (total_qty >= risk.shortage),
        )
    return result
