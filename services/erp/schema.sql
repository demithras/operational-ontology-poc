-- Fake ERP schema. Executed idempotently at service startup (services/erp/app.py).

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id     TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('ACTIVE', 'SUSPENDED')),
    lead_time_days  INT NOT NULL CHECK (lead_time_days >= 0),
    risk_class      TEXT NOT NULL CHECK (risk_class IN ('LOW', 'MEDIUM', 'HIGH')),
    version         INT NOT NULL DEFAULT 1,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS parts (
    part_id      TEXT PRIMARY KEY,
    description  TEXT NOT NULL,
    unit         TEXT NOT NULL,
    criticality  TEXT NOT NULL CHECK (criticality IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    version      INT NOT NULL DEFAULT 1,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_id         TEXT PRIMARY KEY,
    supplier_id   TEXT NOT NULL REFERENCES suppliers (supplier_id),
    status        TEXT NOT NULL CHECK (status IN ('OPEN', 'DELAYED', 'RECEIVED', 'CANCELLED')),
    promised_at   INT NOT NULL,
    expected_at   INT NOT NULL,
    delay_reason  TEXT,
    version       INT NOT NULL DEFAULT 1,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- destination_warehouse is a plain string in WMS's id space: ERP does not
-- own or validate warehouse identity (separate database/service boundary).
CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id                     SERIAL PRIMARY KEY,
    po_id                  TEXT NOT NULL REFERENCES purchase_orders (po_id),
    part_id                TEXT NOT NULL REFERENCES parts (part_id),
    qty                    INT NOT NULL CHECK (qty > 0),
    destination_warehouse  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_po_lines_po_id ON purchase_order_lines (po_id);
CREATE INDEX IF NOT EXISTS idx_po_supplier ON purchase_orders (supplier_id);
