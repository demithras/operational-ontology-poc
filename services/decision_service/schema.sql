-- Phase 5 decision-service index tables, in the `ontology_hot` database
-- (docs/experiment/spec/06_decision_and_action_runtime.md: "Decisions +
-- PROV links live in RDF4J; the Postgres row is only an index" — every
-- column here is DERIVED FROM, never authoritative over, the RDF4J graph
-- written by services/decision_service/rdf_writer.py for the same
-- decision_id). Reuses the `ontology_hot_role` credentials
-- (services/common/db.py) rather than provisioning a new role/database:
-- decision_service and projection_builder are both ontology-layer
-- components sharing the hot-state database, distinct from the
-- source-system credential-isolation boundary (erp/mes/wms) that
-- db/init/00_init.sh enforces — see
-- docs/experiment/implementation-notes.md Phase 5 section.
--
-- Applied idempotently (CREATE TABLE IF NOT EXISTS) at
-- services/decision_service startup, same pattern as every other
-- services/<x>/schema.sql in this repo.

CREATE TABLE IF NOT EXISTS decisions (
    decision_id                    TEXT PRIMARY KEY,
    decision_type                  TEXT NOT NULL,
    actor_type                     TEXT NOT NULL CHECK (actor_type IN ('user', 'agent')),
    actor_id                       TEXT NOT NULL,
    principal_actor_id             TEXT,
    action_type                    TEXT NOT NULL,
    action_version                 INT NOT NULL,
    parameters                     JSONB NOT NULL,
    context                        JSONB NOT NULL DEFAULT '{}'::jsonb,
    status                         TEXT NOT NULL,
    ontology_version                TEXT NOT NULL,
    shape_set_version                TEXT NOT NULL,
    authorization_model_version      TEXT NOT NULL,
    policy_bundle_version             TEXT NOT NULL,
    decision_content_hash              TEXT,
    action_pinned_sha256                TEXT,
    evidence_snapshot_id                TEXT NOT NULL,
    evidence_snapshot                    JSONB NOT NULL,
    authorization_result                  JSONB,
    policy_result                          JSONB,
    conformance_result                      JSONB,
    approved_by                              TEXT,
    approved_at                               TIMESTAMPTZ,
    approval_decision_hash                     TEXT,
    approval_scope                              TEXT,
    rdf_graph                                    TEXT NOT NULL,
    created_at                                    TIMESTAMPTZ NOT NULL,
    updated_at                                     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions (status);
CREATE INDEX IF NOT EXISTS idx_decisions_action_type ON decisions (action_type);

-- Phase 6b / F34 (docs/experiment/implementation-notes.md "ALTER TABLE ...
-- ADD COLUMN IF NOT EXISTS" workaround, same pattern as work_order_risk's
-- `priority` column in Phase 6 step 0): the CREATE TABLE above already
-- declares this column for a from-scratch `make reset`, but an
-- ALREADY-RUNNING stack's `decisions` table predates it — this makes the
-- column show up on the next decision_service restart without a
-- data-losing reset.
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS action_pinned_sha256 TEXT;

-- F22-style "the proposal never even became a governed Decision" record
-- (RDF4J was unreachable, so no SHACL-validated Decision write was even
-- possible — see services/decision_service/app.py's propose() exception
-- handling). NOT a Decision (H1's completeness metric is only over
-- successfully governed decisions) — a lightweight operational log so
-- "component failure causes an explicit unavailable state, not fabricated
-- certainty" (acceptance criterion 11) is still auditable even when nothing
-- could be written to the semantic core at all.
CREATE TABLE IF NOT EXISTS proposal_attempt_failures (
    id                    BIGSERIAL PRIMARY KEY,
    attempted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    action_type           TEXT NOT NULL,
    actor_type            TEXT NOT NULL,
    actor_id              TEXT NOT NULL,
    reason                TEXT NOT NULL,
    detail                TEXT
);
