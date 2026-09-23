-- Fake WMS schema. Executed idempotently at service startup (services/wms/app.py).

CREATE TABLE IF NOT EXISTS warehouses (
    warehouse_id     TEXT PRIMARY KEY,
    capacity_class   TEXT NOT NULL CHECK (capacity_class IN ('SMALL', 'MEDIUM', 'LARGE')),
    region           TEXT NOT NULL,
    version          INT NOT NULL DEFAULT 1,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inventory_lots (
    lot_id          TEXT PRIMARY KEY,
    part            TEXT NOT NULL,
    warehouse_id    TEXT NOT NULL REFERENCES warehouses (warehouse_id),
    on_hand         INT NOT NULL CHECK (on_hand >= 0),
    reserved        INT NOT NULL CHECK (reserved >= 0),
    available       INT GENERATED ALWAYS AS (on_hand - reserved) STORED,
    quality_status  TEXT NOT NULL CHECK (quality_status IN ('OK', 'QUARANTINE')),
    version         INT NOT NULL DEFAULT 1,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT on_hand_ge_reserved CHECK (on_hand >= reserved)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_inventory_part_warehouse ON inventory_lots (part, warehouse_id);

-- One row per action_execution_id (docs/experiment/spec/06:
-- "WMS persists a unique constraint on action_execution_id"). body_hash lets
-- us tell an idempotent replay (same key, same body -> return original)
-- from a genuine conflict (same key, different body -> 409).
CREATE TABLE IF NOT EXISTS transfers (
    action_execution_id           TEXT PRIMARY KEY,
    source_warehouse              TEXT NOT NULL REFERENCES warehouses (warehouse_id),
    destination_warehouse         TEXT NOT NULL REFERENCES warehouses (warehouse_id),
    part                          TEXT NOT NULL,
    requested_quantity            INT NOT NULL CHECK (requested_quantity > 0),
    actual_quantity               INT NOT NULL DEFAULT 0,
    status                        TEXT NOT NULL CHECK (status IN ('COMMITTED', 'PARTIAL', 'FAILED', 'REVERSED')),
    body_hash                     TEXT NOT NULL,
    fault_mode_applied            TEXT,
    reverses_action_execution_id  TEXT REFERENCES transfers (action_execution_id),
    version                       INT NOT NULL DEFAULT 1,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transfers_part_wh ON transfers (part, source_warehouse, destination_warehouse);
