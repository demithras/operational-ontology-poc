"""Writes computed projection rows (services.projection_builder.compute
dataclasses) into the ontology_hot Postgres tables, stamping every row with
the traceability columns docs/experiment/briefs/phase4.md item 1 requires.

Each build cycle DELETEs and re-INSERTs all four tables inside ONE
transaction (services/projection_builder/builder.py commits at the end) —
simplest possible implementation that is trivially correct (no incremental-
update bugs to get wrong) and, because Postgres readers under the default
READ COMMITTED isolation only ever see a transaction's state before or
after COMMIT, concurrent hot reads never observe a half-rebuilt table.

Phase 10a step 0a fix: this used to be `TRUNCATE <table>`, which takes an
AccessExclusiveLock — the strongest lock Postgres has, incompatible with
even a plain reader's AccessShareLock. A real, reproducible deadlock
(services/decision_service/app.py's own `_EVIDENCE_DEADLOCK_RETRIES`
comment documents it) came from exactly this: a decision_service evidence
read taking AccessShareLock on work_order_risk then waiting on
transfer_candidates, racing a rebuild TRUNCATEing them in the same order —
classic AB-BA lock-order collision, except one side (TRUNCATE) needed the
strongest lock Postgres offers to do work a weaker one would have covered
just as well. `DELETE FROM <table>` (no `WHERE`) deletes every row exactly
like TRUNCATE, but only takes a RowExclusiveLock — compatible with
concurrent AccessShareLock readers; only actual row-level writers can
conflict with it, and the four tables in this module have no other
writer. Lock ORDER here was already globally consistent before this fix
(this module is the tables' only writer, and builder.py calls these four
functions in the same fixed order — work_order_risk, transfer_candidates,
current_inventory, action_eligibility_summary — every single build cycle,
live poll or rebuild alike) — only the lock STRENGTH was the problem.
Readers no longer need to retry on DeadlockDetected because of a rebuild
in progress; see tests/integration/test_projection_rebuild_concurrency.py
for a live proof (rebuild loop + 8 concurrent proposers, >=60s, zero
deadlocks). The evidence-path retry loop in
services/decision_service/app.py is left in place as defense in depth
(harmless, no longer exercised by this specific cause) rather than
removed, per this phase's "remove any NEED for deadlock retries" wording —
the retries becoming dead code IS the proof the fix worked.
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
        cur.execute("DELETE FROM work_order_risk")
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
        cur.execute("DELETE FROM transfer_candidates")
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
        cur.execute("DELETE FROM current_inventory")
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
        cur.execute("DELETE FROM action_eligibility_summary")
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
