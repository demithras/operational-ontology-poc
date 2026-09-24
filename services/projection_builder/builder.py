"""One full build cycle: RDF4J (via SPARQL) -> compute -> ontology_hot
Postgres. Used by both the live poll loop (services/projection_builder/
main.py) and `make rebuild-projections` (services/projection_builder/
rebuild.py) — same function, so "rebuild from scratch" and "one poll tick"
are provably the same code path (docs/experiment/spec/07_versioning_and_replay.md
"Projection rebuild": "Delete all hot projections and reconstruct them from
semantic/source history").
"""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

from services.common.rdf4j_client import RDF4JClient
from services.projection_builder import rdf_reader, writer
from services.projection_builder.compute import (
    compute_action_eligibility_summary,
    compute_current_inventory,
    compute_transfer_candidates,
    compute_work_order_risk,
)
from services.projection_builder.definitions import ProjectionDefinition, load_all_definitions


@dataclass(frozen=True)
class BuildStats:
    work_order_risk_rows: int
    transfer_candidates_rows: int
    current_inventory_rows: int
    action_eligibility_summary_rows: int
    definitions: dict[str, ProjectionDefinition]


def build_all(client: RDF4JClient, conn: psycopg.Connection) -> BuildStats:
    # Phase 10a step 0a fix, part 2 (found via this phase's OWN concurrency
    # test, tests/integration/test_projection_rebuild_concurrency.py):
    # switching services/projection_builder/writer.py's TRUNCATE ->
    # DELETE FROM (to stop blocking READERS) also removed the WRITER-vs-
    # WRITER mutual exclusion TRUNCATE's AccessExclusiveLock used to give
    # for free. Two genuinely concurrent build_all() calls (the live poll
    # loop + a manual `make rebuild-projections`, or two manual runs) can
    # interleave their own independent DELETE-then-INSERT cycles across
    # the SAME table and hit `work_order_risk_pkey`/etc UniqueViolation —
    # reproduced live. A `pg_advisory_xact_lock` is the right primitive
    # here: it serializes WRITERS against each other (this function's own
    # transaction, auto-released at COMMIT/ROLLBACK) while being
    # completely invisible to plain SELECT readers (advisory locks never
    # interact with regular table-level locks), so the original AB-BA
    # deadlock this step fixes cannot come back. Same
    # `hashtextextended(key, 0)` idiom services/wms/transfers.py already
    # uses for its own per-key advisory lock — one fixed key here since
    # there is exactly one shared "the hot projections" resource, not one
    # per row.
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtextextended('oo_poc_projection_rebuild', 0))")

    definitions = load_all_definitions()
    computed_at = writer.now_utc()

    position_index = rdf_reader.fetch_source_positions(client)

    wor_def = definitions["work_order_risk"]
    work_orders = rdf_reader.run_query(client, wor_def.queries["work_orders"])
    requirements = rdf_reader.run_query(client, wor_def.queries["requirements"])
    inventory_available = rdf_reader.run_query(client, wor_def.queries["inventory_available"])
    incoming_lines = rdf_reader.run_query(client, wor_def.queries["incoming_purchase_lines"])

    risk_rows = compute_work_order_risk(work_orders, requirements, inventory_available, incoming_lines)
    candidate_rows = compute_transfer_candidates(risk_rows, inventory_available)
    summary_rows = compute_action_eligibility_summary(risk_rows, candidate_rows)

    ci_def = definitions["current_inventory"]
    inventory_lots = rdf_reader.run_query(client, ci_def.queries["inventory_lots"])
    inventory_rows = compute_current_inventory(inventory_lots)

    contributing_by_wo = {wo_id: r.contributing_entities for wo_id, r in risk_rows.items()}

    stamped_risk = writer.write_work_order_risk(conn, risk_rows, position_index, wor_def, computed_at)
    stamped_candidates = writer.write_transfer_candidates(
        conn, candidate_rows, position_index, definitions["transfer_candidates"], computed_at
    )
    stamped_inventory = writer.write_current_inventory(conn, inventory_rows, position_index, ci_def, computed_at)
    stamped_summary = writer.write_action_eligibility_summary(
        conn,
        summary_rows,
        position_index,
        definitions["action_eligibility_summary"],
        computed_at,
        contributing_by_wo,
    )
    conn.commit()

    return BuildStats(
        work_order_risk_rows=len(stamped_risk),
        transfer_candidates_rows=len(stamped_candidates),
        current_inventory_rows=len(stamped_inventory),
        action_eligibility_summary_rows=len(stamped_summary),
        definitions=definitions,
    )
