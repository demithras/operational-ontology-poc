"""Writes computed projection rows (services.projection_builder.compute
dataclasses) into the ontology_hot Postgres tables, stamping every row with
the traceability columns docs/experiment/briefs/phase4.md item 1 requires.

Each build cycle TRUNCATEs and re-INSERTs all four tables inside ONE
transaction (services/projection_builder/builder.py commits at the end) —
simplest possible implementation that is trivially correct (no incremental-
update bugs to get wrong) and, because Postgres readers under the default
READ COMMITTED isolation only ever see a transaction's state before or
after COMMIT, concurrent hot reads never observe a half-rebuilt table.
"""

from __future__ import annotations

from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Json

from services.common.contract_versions import ONTOLOGY_CONTRACT_VERSION
from services.projection_builder.compute import (
    ActionEligibilitySummaryRow,
    CurrentInventoryRow,
    TransferCandidateRow,
    WorkOrderRiskRow,
)
from services.projection_builder.definitions import ProjectionDefinition
from services.projection_builder.hashing import row_content_hash
from services.projection_builder.provenance import PositionIndex, build_source_positions, latest_observed_at


def _stamp(
    table: str,
    business_fields: dict,
    contributing_entities: tuple,
    position_index: PositionIndex,
    definition: ProjectionDefinition,
    computed_at: datetime,
) -> dict:
    source_positions = build_source_positions(contributing_entities, position_index)
    row = dict(business_fields)
    row["source_positions"] = source_positions
    row["projection_definition_name"] = definition.name
    row["projection_definition_version"] = definition.version
    row["projection_definition_sha256"] = definition.sha256
    row["ontology_contract_version"] = ONTOLOGY_CONTRACT_VERSION
    row["computed_at"] = computed_at
    row["as_of"] = latest_observed_at(source_positions, fallback=computed_at)
    row["content_hash"] = row_content_hash(table, row)
    return row


def write_work_order_risk(
    conn: psycopg.Connection,
    rows: dict[str, WorkOrderRiskRow],
    position_index: PositionIndex,
    definition: ProjectionDefinition,
    computed_at: datetime,
) -> list[dict]:
    stamped = [
        _stamp(
            "work_order_risk",
            {
                "work_order_id": r.work_order_id,
                "warehouse": r.warehouse,
                "shortage": r.shortage,
                "at_risk": r.at_risk,
                "severity": r.severity,
                "priority": r.priority,
            },
            r.contributing_entities,
            position_index,
            definition,
            computed_at,
        )
        for r in rows.values()
    ]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE work_order_risk")
        for row in stamped:
            cur.execute(
                """
                INSERT INTO work_order_risk
                    (work_order_id, warehouse, shortage, at_risk, severity, priority, content_hash,
                     source_positions, projection_definition_name, projection_definition_version,
                     projection_definition_sha256, ontology_contract_version, computed_at, as_of)
                VALUES (%(work_order_id)s, %(warehouse)s, %(shortage)s, %(at_risk)s, %(severity)s,
                        %(priority)s, %(content_hash)s, %(source_positions)s, %(projection_definition_name)s,
                        %(projection_definition_version)s, %(projection_definition_sha256)s,
                        %(ontology_contract_version)s, %(computed_at)s, %(as_of)s)
                """,
                {**row, "source_positions": Json(row["source_positions"])},
            )
    return stamped


def write_transfer_candidates(
    conn: psycopg.Connection,
    rows: list[TransferCandidateRow],
    position_index: PositionIndex,
    definition: ProjectionDefinition,
    computed_at: datetime,
) -> list[dict]:
    stamped = [
        _stamp(
            "transfer_candidates",
            {
                "candidate_id": r.candidate_id,
                "work_order_id": r.work_order_id,
                "part": r.part,
                "destination_warehouse": r.destination_warehouse,
                "source_warehouse": r.source_warehouse,
                "candidate_quantity": r.candidate_quantity,
                "available_at_source": r.available_at_source,
            },
            r.contributing_entities,
            position_index,
            definition,
            computed_at,
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE transfer_candidates")
        for row in stamped:
            cur.execute(
                """
                INSERT INTO transfer_candidates
                    (candidate_id, work_order_id, part, destination_warehouse, source_warehouse,
                     candidate_quantity, available_at_source, content_hash, source_positions,
                     projection_definition_name, projection_definition_version,
                     projection_definition_sha256, ontology_contract_version, computed_at, as_of)
                VALUES (%(candidate_id)s, %(work_order_id)s, %(part)s, %(destination_warehouse)s,
                        %(source_warehouse)s, %(candidate_quantity)s, %(available_at_source)s,
                        %(content_hash)s, %(source_positions)s, %(projection_definition_name)s,
                        %(projection_definition_version)s, %(projection_definition_sha256)s,
                        %(ontology_contract_version)s, %(computed_at)s, %(as_of)s)
                """,
                {**row, "source_positions": Json(row["source_positions"])},
            )
    return stamped


def write_current_inventory(
    conn: psycopg.Connection,
    rows: list[CurrentInventoryRow],
    position_index: PositionIndex,
    definition: ProjectionDefinition,
    computed_at: datetime,
) -> list[dict]:
    stamped = [
        _stamp(
            "current_inventory",
            {
                "part": r.part,
                "warehouse": r.warehouse,
                "on_hand": r.on_hand,
                "reserved": r.reserved,
                "available": r.available,
                "quality_status": r.quality_status,
            },
            r.contributing_entities,
            position_index,
            definition,
            computed_at,
        )
        for r in rows
    ]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE current_inventory")
        for row in stamped:
            cur.execute(
                """
                INSERT INTO current_inventory
                    (part, warehouse, on_hand, reserved, available, quality_status, content_hash,
                     source_positions, projection_definition_name, projection_definition_version,
                     projection_definition_sha256, ontology_contract_version, computed_at, as_of)
                VALUES (%(part)s, %(warehouse)s, %(on_hand)s, %(reserved)s, %(available)s,
                        %(quality_status)s, %(content_hash)s, %(source_positions)s,
                        %(projection_definition_name)s, %(projection_definition_version)s,
                        %(projection_definition_sha256)s, %(ontology_contract_version)s,
                        %(computed_at)s, %(as_of)s)
                """,
                {**row, "source_positions": Json(row["source_positions"])},
            )
    return stamped


def write_action_eligibility_summary(
    conn: psycopg.Connection,
    rows: dict[str, ActionEligibilitySummaryRow],
    position_index: PositionIndex,
    definition: ProjectionDefinition,
    computed_at: datetime,
    contributing_entities_by_wo: dict[str, tuple],
) -> list[dict]:
    stamped = [
        _stamp(
            "action_eligibility_summary",
            {
                "work_order_id": r.work_order_id,
                "at_risk": r.at_risk,
                "shortage": r.shortage,
                "severity": r.severity,
                "transfer_candidate_count": r.transfer_candidate_count,
                "max_single_candidate_quantity": r.max_single_candidate_quantity,
                "total_candidate_quantity": r.total_candidate_quantity,
                "mitigation_feasible": r.mitigation_feasible,
            },
            contributing_entities_by_wo.get(r.work_order_id, ()),
            position_index,
            definition,
            computed_at,
        )
        for r in rows.values()
    ]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE action_eligibility_summary")
        for row in stamped:
            cur.execute(
                """
                INSERT INTO action_eligibility_summary
                    (work_order_id, at_risk, shortage, severity, transfer_candidate_count,
                     max_single_candidate_quantity, total_candidate_quantity, mitigation_feasible,
                     content_hash, source_positions, projection_definition_name,
                     projection_definition_version, projection_definition_sha256,
                     ontology_contract_version, computed_at, as_of)
                VALUES (%(work_order_id)s, %(at_risk)s, %(shortage)s, %(severity)s,
                        %(transfer_candidate_count)s, %(max_single_candidate_quantity)s,
                        %(total_candidate_quantity)s, %(mitigation_feasible)s, %(content_hash)s,
                        %(source_positions)s, %(projection_definition_name)s,
                        %(projection_definition_version)s, %(projection_definition_sha256)s,
                        %(ontology_contract_version)s, %(computed_at)s, %(as_of)s)
                """,
                {**row, "source_positions": Json(row["source_positions"])},
            )
    return stamped


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
