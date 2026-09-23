-- Fake MES schema. Executed idempotently at service startup (services/mes/app.py).

CREATE TABLE IF NOT EXISTS production_lines (
    line_id       TEXT PRIMARY KEY,
    status        TEXT NOT NULL CHECK (status IN ('ACTIVE', 'MAINTENANCE')),
    capabilities  JSONB NOT NULL DEFAULT '[]'::jsonb,
    version       INT NOT NULL DEFAULT 1,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- warehouse is a plain string in WMS's id space (cross-service boundary,
-- same rationale as purchase_order_lines.destination_warehouse in ERP).
CREATE TABLE IF NOT EXISTS work_orders (
    work_order_id       TEXT PRIMARY KEY,
    production_line_id  TEXT NOT NULL REFERENCES production_lines (line_id),
    status              TEXT NOT NULL CHECK (status IN ('PLANNED', 'RELEASED', 'RUNNING', 'DONE', 'CANCELLED')),
    priority            TEXT NOT NULL CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH')),
    planned_start       INT NOT NULL,
    planned_finish      INT NOT NULL,
    warehouse           TEXT NOT NULL,
    version             INT NOT NULL DEFAULT 1,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bom_requirements (
    id             SERIAL PRIMARY KEY,
    work_order_id  TEXT NOT NULL REFERENCES work_orders (work_order_id),
    part_id        TEXT NOT NULL,
    qty            INT NOT NULL CHECK (qty > 0)
);

CREATE INDEX IF NOT EXISTS idx_bom_work_order_id ON bom_requirements (work_order_id);
CREATE INDEX IF NOT EXISTS idx_wo_production_line ON work_orders (production_line_id);
