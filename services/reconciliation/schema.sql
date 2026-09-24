-- services/reconciliation's own index table, in the `ontology_hot` database
-- (same shared-hot-state-database convention as services/decision_service/schema.sql
-- and services/projection_builder/schema.sql — all three are ontology-layer
-- components, distinct from the source-system credential-isolation
-- boundary erp/mes/wms enforce).
--
-- H12 ("independent reality-check... on divergence, raise a reconciliation
-- alert record with expected, observed, action/decision, source evidence,
-- retry/compensation status"). RDF4J already holds the authoritative
-- oo:Outcome per decision (services/common/action_rdf.py) — this table is
-- an OPERATIONAL WORKLIST/LOG for the reconciliation poll loop itself: which
-- decisions are still being watched, and a durable alert record for every
-- DIVERGED one, queryable without a SPARQL round trip.
CREATE TABLE IF NOT EXISTS reconciliation_alerts (
    id                       BIGSERIAL PRIMARY KEY,
    decision_id              TEXT NOT NULL,
    action_execution_id      TEXT NOT NULL,
    expected_effect_json     JSONB NOT NULL,
    observed_effect_json     JSONB NOT NULL,
    compensation_status      TEXT NOT NULL,
    detected_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (action_execution_id)
);

CREATE TABLE IF NOT EXISTS reconciliation_convergences (
    id                       BIGSERIAL PRIMARY KEY,
    decision_id              TEXT NOT NULL,
    action_execution_id      TEXT NOT NULL,
    old_reconciliation_state TEXT NOT NULL,
    new_reconciliation_state TEXT NOT NULL,
    converged_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (action_execution_id, new_reconciliation_state)
);
