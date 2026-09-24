-- Phase 4 hot-projection tables in the ontology_hot database
-- (docs/experiment/spec/04_architecture.md "PostgreSQL hot projections").
-- Applied idempotently (CREATE TABLE IF NOT EXISTS) at
-- services/projection_builder startup, same pattern as
-- services/erp|mes|wms/schema.sql.
--
-- Every table shares the same traceability columns (item 1 of
-- docs/experiment/briefs/phase4.md): source_positions (per-contributing-
-- entity LSN/version), projection_definition_name/version/sha256
-- (contracts/projections/v1/*.yaml), ontology_contract_version,
-- computed_at (wall-clock build time) and as_of (latest observed_at among
-- contributing source positions — see services/projection_builder/
-- provenance.py::latest_observed_at). freshness (FRESH/STALE) is
-- deliberately NOT a stored column — see services/projection_builder/
-- freshness.py's docstring for why storing it would itself go stale.
-- content_hash is a sha256 over each row's own deterministic BUSINESS
-- fields only (never computed_at/as_of/source_positions/itself) — used by
-- the F27 corrupt-projection consistency check
-- (services/projection_builder/consistency.py) and documents exactly which
-- columns docs/experiment/spec/07_versioning_and_replay.md's rebuild-hash
-- test excludes.

CREATE TABLE IF NOT EXISTS work_order_risk (
    work_order_id                  TEXT PRIMARY KEY,
    warehouse                      TEXT NOT NULL,
    shortage                       INT NOT NULL,
    at_risk                        BOOLEAN NOT NULL,
    severity                       TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'MITIGATED')),
    -- Phase 6 step 0 security fix (docs/adr/0003-protected-high-priority-transfer-authorization.md):
    -- fac:priority passed through unchanged, so decision_service can
    -- resolve "does this transfer mitigate a HIGH-priority at-risk work
    -- order" from the SAME freshness-governed evidence path as every other
    -- gate input, never from a live fail-open MES call. Nullable (not
    -- NOT NULL) purely so `ALTER TABLE ... ADD COLUMN` below is safe against
    -- an already-running Phase 4/5 stack's existing rows before the next
    -- rebuild cycle overwrites them (every build_all() TRUNCATEs+re-INSERTs
    -- the whole table, so the null window is at most one poll interval).
    priority                       TEXT CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH')),
    content_hash                   TEXT NOT NULL,
    source_positions               JSONB NOT NULL DEFAULT '[]'::jsonb,
    projection_definition_name     TEXT NOT NULL,
    projection_definition_version  TEXT NOT NULL,
    projection_definition_sha256   TEXT NOT NULL,
    ontology_contract_version      TEXT NOT NULL,
    computed_at                    TIMESTAMPTZ NOT NULL,
    as_of                          TIMESTAMPTZ NOT NULL
);

-- Idempotent migration for an already-running stack created before this
-- column existed (CREATE TABLE IF NOT EXISTS above is a no-op against an
-- existing table) — see the column comment above for why nullable is safe.
ALTER TABLE work_order_risk ADD COLUMN IF NOT EXISTS priority TEXT CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH'));

CREATE TABLE IF NOT EXISTS transfer_candidates (
    candidate_id                   TEXT PRIMARY KEY,
    work_order_id                  TEXT NOT NULL,
    part                           TEXT NOT NULL,
    destination_warehouse          TEXT NOT NULL,
    source_warehouse               TEXT NOT NULL,
    candidate_quantity             INT NOT NULL,
    available_at_source            INT NOT NULL,
    content_hash                   TEXT NOT NULL,
    source_positions               JSONB NOT NULL DEFAULT '[]'::jsonb,
    projection_definition_name     TEXT NOT NULL,
    projection_definition_version  TEXT NOT NULL,
    projection_definition_sha256   TEXT NOT NULL,
    ontology_contract_version      TEXT NOT NULL,
    computed_at                    TIMESTAMPTZ NOT NULL,
    as_of                          TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transfer_candidates_wo ON transfer_candidates (work_order_id);

CREATE TABLE IF NOT EXISTS current_inventory (
    part                           TEXT NOT NULL,
    warehouse                      TEXT NOT NULL,
    on_hand                        INT NOT NULL,
    reserved                       INT NOT NULL,
    available                      INT NOT NULL,
    quality_status                 TEXT NOT NULL,
    content_hash                   TEXT NOT NULL,
    source_positions               JSONB NOT NULL DEFAULT '[]'::jsonb,
    projection_definition_name     TEXT NOT NULL,
    projection_definition_version  TEXT NOT NULL,
    projection_definition_sha256   TEXT NOT NULL,
    ontology_contract_version      TEXT NOT NULL,
    computed_at                    TIMESTAMPTZ NOT NULL,
    as_of                          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (part, warehouse)
);

CREATE TABLE IF NOT EXISTS action_eligibility_summary (
    work_order_id                   TEXT PRIMARY KEY,
    at_risk                         BOOLEAN NOT NULL,
    shortage                        INT NOT NULL,
    severity                        TEXT NOT NULL,
    transfer_candidate_count        INT NOT NULL,
    max_single_candidate_quantity   INT NOT NULL,
    total_candidate_quantity        INT NOT NULL,
    mitigation_feasible             BOOLEAN NOT NULL,
    content_hash                    TEXT NOT NULL,
    source_positions                JSONB NOT NULL DEFAULT '[]'::jsonb,
    projection_definition_name      TEXT NOT NULL,
    projection_definition_version   TEXT NOT NULL,
    projection_definition_sha256    TEXT NOT NULL,
    ontology_contract_version       TEXT NOT NULL,
    computed_at                     TIMESTAMPTZ NOT NULL,
    as_of                           TIMESTAMPTZ NOT NULL
);
