-- Phase 8 (A/B experiment, Variant A — "conventional service architecture",
-- docs/experiment/spec/10_ab_experiment.md): the baseline's OWN relational
-- domain model, in the `baseline` database (db/init/00_init.sh already
-- provisions BASELINE_DB_NAME/BASELINE_DB_USER — reserved since Phase 2).
-- Applied idempotently (CREATE TABLE IF NOT EXISTS) at
-- services/baseline/app.py and services/baseline/consumer.py startup, same
-- pattern as every other services/<x>/schema.sql in this repo.
--
-- Two families of tables:
--   1. A REPLICA of the ERP/MES/WMS source data, maintained by
--      services/baseline/consumer.py's OWN Debezium consumer group
--      (fairness rule: "same CDC observation path", spec 10) — this
--      variant's entire "semantic core" is just these plain tables, no RDF,
--      no hot-projection poll/rebuild layer: evidence is computed ON
--      DEMAND from here (services/baseline/evidence.py), not precomputed.
--   2. The decision/audit tables — genuinely normalized (a real gate_results
--      table, not just a JSONB blob dump) per the brief's "make it GOOD, a
--      strawman is invalid".

-- =========================================================================
-- 1. Source replica (fed by services/baseline/consumer.py)
-- =========================================================================

CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id     TEXT PRIMARY KEY,
    capacity_class   TEXT,
    region           TEXT,
    source_version   INT,
    cdc_applied_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- `part` is always the CANONICAL id (services/identity_resolver's
-- resolution, applied by the consumer at CDC-apply time — see
-- identity_mapping below) so every downstream query (evidence, compute.py)
-- joins on one consistent identifier space, exactly like the ontology
-- variant's fac:Part IRIs do.
CREATE TABLE IF NOT EXISTS inventory_lots (
    lot_id           TEXT PRIMARY KEY,
    part             TEXT NOT NULL,
    warehouse_id     TEXT NOT NULL,
    on_hand          INT NOT NULL,
    reserved         INT NOT NULL,
    quality_status   TEXT NOT NULL,
    source_version   INT,
    cdc_applied_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_inventory_lots_part_wh ON inventory_lots (part, warehouse_id);

CREATE TABLE IF NOT EXISTS work_orders (
    work_order_id    TEXT PRIMARY KEY,
    warehouse_id     TEXT,
    status           TEXT NOT NULL,
    priority         TEXT NOT NULL,
    planned_start    BIGINT,
    source_version   INT,
    cdc_applied_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bom_requirements (
    req_id           TEXT PRIMARY KEY,
    work_order_id    TEXT NOT NULL,
    part             TEXT NOT NULL,
    qty              INT NOT NULL,
    cdc_applied_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bom_requirements_wo ON bom_requirements (work_order_id);

-- expected_at/promised_at live on the ORDER (matching services/erp/schema.sql
-- exactly — ERP has no per-line expected date), joined per-line via po_id
-- the same way contracts/projections/v1/work_order_risk.yaml's SPARQL does
-- (?line fac:purchaseOrder ?po . ?po fac:expectedAt ?expectedAt).
CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id            TEXT PRIMARY KEY,
    supplier_id      TEXT,
    status           TEXT NOT NULL,
    expected_at      BIGINT,
    source_version   INT,
    cdc_applied_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    line_id            TEXT PRIMARY KEY,
    po_id              TEXT NOT NULL,
    part               TEXT NOT NULL,
    destination_wh     TEXT,
    qty                INT NOT NULL,
    cdc_applied_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_po_lines_part_wh ON purchase_order_lines (part, destination_wh);

CREATE TABLE IF NOT EXISTS parts (
    part_id          TEXT PRIMARY KEY,   -- ERP's own local part id (parts table is ERP-owned)
    name             TEXT,
    status           TEXT,
    source_version   INT,
    cdc_applied_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The CDC-observed counterpart to a WMS POST /transfers command — same
-- role as the ontology variant's fac:WmsTransferRecord
-- (services/common/wms_transfer_observation.py), just a plain row instead
-- of an RDF resource.
CREATE TABLE IF NOT EXISTS wms_transfer_records (
    action_execution_id   TEXT PRIMARY KEY,
    status                 TEXT NOT NULL,
    requested_quantity     INT NOT NULL,
    actual_quantity        INT NOT NULL,
    cdc_applied_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- services/baseline/consumer.py's OWN relational identity-mapping table
-- (spec 10: "its own relational identity mapping table") — same
-- services/identity_resolver.IdentityResolver algorithm as the ontology
-- variant (contracts/identity/v1/mapping_rules.yaml, reused verbatim: a
-- deliberate fairness choice, see docs/experiment/implementation-notes.md
-- Phase 8 section — "same business semantics" should not depend on which
-- storage technology interprets the same rules), just persisted as a row
-- instead of an oo:IdentityMapping RDF resource.
CREATE TABLE IF NOT EXISTS identity_mapping (
    system              TEXT NOT NULL,
    source_local_id     TEXT NOT NULL,
    canonical_id        TEXT NOT NULL,
    rule_id             TEXT NOT NULL,
    rule_version        TEXT NOT NULL,
    authority           TEXT NOT NULL,
    confidence          REAL NOT NULL,
    resolved_at         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (system, source_local_id)
);
CREATE INDEX IF NOT EXISTS idx_identity_mapping_canonical ON identity_mapping (canonical_id);

-- F09 ("ambiguous identity never auto-merges silently"): an unresolved
-- source-local id is recorded here, never silently guessed — the
-- relational equivalent of the ontology variant's oo:Quarantined resource.
CREATE TABLE IF NOT EXISTS quarantined_identities (
    system              TEXT NOT NULL,
    source_local_id     TEXT NOT NULL,
    reason              TEXT NOT NULL,
    resolved_at         TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (system, source_local_id)
);

-- The freshness signal services/baseline/evidence.py reads (spec 04's
-- consistency model: FRESH/STALE/...) — ONE row per source system, touched
-- on every consumed message (a real CDC event OR a Debezium heartbeat),
-- same "advances even when nothing changed" semantics as the ontology
-- variant's ingestion watermark, just a table instead of an in-process
-- HealthState dict read over HTTP. Simpler by construction: this variant
-- has no separate hot-projection rebuild step, so there is only ONE
-- watermark to check, not two (see services/baseline/evidence.py's own
-- docstring for the direct comparison).
CREATE TABLE IF NOT EXISTS ingestion_watermarks (
    system              TEXT PRIMARY KEY,
    last_applied_at     TIMESTAMPTZ NOT NULL
);

-- =========================================================================
-- 2. Decision + audit tables (services/baseline/store.py)
-- =========================================================================

CREATE TABLE IF NOT EXISTS decisions (
    decision_id                  TEXT PRIMARY KEY,
    decision_type                TEXT NOT NULL,
    actor_type                   TEXT NOT NULL CHECK (actor_type IN ('user', 'agent')),
    actor_id                     TEXT NOT NULL,
    principal_actor_id           TEXT,
    action_type                  TEXT NOT NULL,
    action_version               INT NOT NULL,
    action_version_dir           TEXT NOT NULL,
    action_pinned_sha256          TEXT,
    parameters                    JSONB NOT NULL,
    context                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- The relational analogue of decision-shape.ttl's sh:in enumeration
    -- (spec 10: "normal schema constraints") — a real Postgres CHECK, not
    -- merely application-level validation, so an invalid status is
    -- rejected at the storage layer exactly like the ontology variant's
    -- SHACL gate rejects an out-of-scheme oo:status. Kept in exact sync
    -- with services/baseline/models.py's status constants.
    status                          TEXT NOT NULL CHECK (status IN (
        'DRAFT', 'PROPOSED', 'INSUFFICIENT_EVIDENCE', 'DENIED_AUTHORIZATION',
        'DENIED_POLICY', 'GATE_UNAVAILABLE', 'REQUIRES_APPROVAL', 'APPROVED',
        'EXECUTING', 'EXECUTION_FAILED', 'OUTCOME_UNKNOWN', 'AWAITING_OBSERVATION',
        'DIVERGED', 'OBSERVED_SUCCESS', 'ACTION_VERSION_INVALIDATED'
    )),
    -- No ontology_version/shape_set_version (this variant has no RDF
    -- semantic core to version) — authorization_model_version/
    -- policy_bundle_version/identity_mapping_version are the SAME
    -- content-addressed tag scheme (services/decision_service/manifest.py's
    -- content_addressed(), reused verbatim) over the SAME shared
    -- contracts/authorization|policies|identity/ trees, since both variants
    -- read identical contract files (fairness rule 4).
    authorization_model_version      TEXT NOT NULL,
    policy_bundle_version             TEXT NOT NULL,
    identity_mapping_version           TEXT NOT NULL,
    openfga_authorization_model_id      TEXT,
    evidence_snapshot_id                 TEXT NOT NULL,
    evidence_snapshot                     JSONB NOT NULL,
    decision_content_hash                  TEXT,
    unavailable_gate                        TEXT,
    approved_by                              TEXT,
    approved_at                               TIMESTAMPTZ,
    approval_decision_hash                     TEXT,
    approval_scope                              TEXT,
    created_at                                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                                    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_baseline_decisions_status ON decisions (status);
CREATE INDEX IF NOT EXISTS idx_baseline_decisions_action_type ON decisions (action_type);

-- The "well-designed relational audit table" the brief specifically asks
-- for: ONE ROW PER GATE EVALUATION, normalized out of `decisions` rather
-- than folded into a JSONB blob — a genuinely different (and in this one
-- respect arguably BETTER-normalized than the RDF variant's
-- oo:AuthorizationCheck/oo:PolicyEvaluation resources, which still get
-- serialized back out as JSON strings for their reasons/obligations
-- payloads) relational design choice: a query like "every DENIED policy
-- evaluation this month" is a plain indexed WHERE clause here, vs a SPARQL
-- traversal there.
CREATE TABLE IF NOT EXISTS gate_results (
    id                BIGSERIAL PRIMARY KEY,
    decision_id       TEXT NOT NULL REFERENCES decisions (decision_id),
    gate_type         TEXT NOT NULL CHECK (gate_type IN ('authorization', 'policy')),
    outcome           TEXT NOT NULL,
    relation_or_package TEXT,
    object_or_input_hash TEXT,
    detail            TEXT,
    reasons           JSONB,
    obligations       JSONB,
    input_json        JSONB,
    model_id_or_bundle_sha TEXT,
    -- authorization gate only: the OpenFGA authorization_model_id this
    -- specific Check was evaluated against, and the store's WHOLE tuple
    -- population at check time (authz.check()'s capture_tuples_snapshot,
    -- Phase 7b's ADR-0004 mechanism) — captured here too so this variant's
    -- authorization REPLAY can achieve the same "live" mode (re-Check
    -- against the historical tuple snapshot) as the ontology variant, not
    -- a structurally weaker "recorded_only" by omission. See
    -- services/baseline/replay.py.
    authorization_model_id TEXT,
    tuples_snapshot   JSONB,
    evaluated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gate_results_decision ON gate_results (decision_id);
CREATE INDEX IF NOT EXISTS idx_gate_results_type_outcome ON gate_results (gate_type, outcome);

CREATE TABLE IF NOT EXISTS action_executions (
    action_execution_id   TEXT PRIMARY KEY,
    decision_id            TEXT NOT NULL REFERENCES decisions (decision_id),
    external_system          TEXT,
    external_operation        TEXT,
    temporal_workflow_id       TEXT,
    command_status               TEXT,
    command_receipt               JSONB,
    started_at                     TIMESTAMPTZ,
    completed_at                    TIMESTAMPTZ,
    status                            TEXT NOT NULL DEFAULT 'EXECUTING'
);
CREATE INDEX IF NOT EXISTS idx_action_executions_decision ON action_executions (decision_id);

CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id                        TEXT PRIMARY KEY,
    action_execution_id                TEXT NOT NULL REFERENCES action_executions (action_execution_id),
    reconciliation_state                TEXT NOT NULL,
    expected_effect                      JSONB,
    observed_effect                       JSONB,
    observed_at                            TIMESTAMPTZ,
    compensation_status                     TEXT,
    compensating_action_execution_id         TEXT
);

CREATE TABLE IF NOT EXISTS proposal_attempt_failures (
    id                    BIGSERIAL PRIMARY KEY,
    attempted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    action_type           TEXT NOT NULL,
    actor_type            TEXT NOT NULL,
    actor_id              TEXT NOT NULL,
    reason                TEXT NOT NULL,
    detail                TEXT
);
