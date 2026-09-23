"""Loads the generated dataset + canonical incident fixture into the WMS
database.

Design decision: seed/generators/generate.py produces 10,000 raw
inventory_lots rows over only 500 parts x 4 warehouses (= 2,000 possible
(part, warehouse) pairs) purely to hit the Phase-0-locked data-volume target
(docs/experiment/spec/02_scope_and_non_goals.md). Loaded 1:1 that would
collide with WMS's `UNIQUE (part, warehouse_id)` index (services/wms/schema.sql)
and with reference_model.state's InventoryLot, which is keyed one-per-
(part, warehouse). This loader therefore AGGREGATES the raw rows into one
operational lot per (part, warehouse) pair — summing on_hand/reserved
(both stay non-negative and on_hand >= reserved, since that already holds
per raw row) and marking the aggregate QUARANTINE if any contributing raw
lot was QUARANTINE (conservative). The 10,000-row volume target is still
met by the generator's *output*; it is a pre-aggregation batch/receiving
view, not the WMS's own operational shape.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import psycopg

DEFAULT_CAPACITY_CLASS = "MEDIUM"  # fixture warehouses don't specify one


def _aggregate_lots(raw_lots: list[dict[str, Any]], parts_local: dict[str, dict[str, str | None]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for lot in raw_lots:
        wms_part = parts_local[lot["part"]]["WMS"]
        key = (wms_part, lot["warehouse"])
        if key not in groups:
            groups[key] = {
                "lot_id": f"LOT-{lot['warehouse']}-{wms_part}",
                "part": wms_part,
                "warehouse_id": lot["warehouse"],
                "on_hand": 0,
                "reserved": 0,
                "quality_status": "OK",
            }
        g = groups[key]
        g["on_hand"] += lot["on_hand"]
        g["reserved"] += lot["reserved"]
        if lot["quality_status"] == "QUARANTINE":
            g["quality_status"] = "QUARANTINE"
    return list(groups.values())


def load(conn: psycopg.Connection, dataset: dict[str, Any], canonical: dict[str, Any], parts_local: dict[str, dict[str, str | None]]) -> None:
    with conn.cursor() as cur:
        wh_rows = [
            {"warehouse_id": w["warehouse_id"], "capacity_class": w["capacity_class"], "region": w["region"]}
            for w in dataset["warehouses"]
        ]
        cur.executemany(
            "INSERT INTO warehouses (warehouse_id, capacity_class, region) "
            "VALUES (%(warehouse_id)s, %(capacity_class)s, %(region)s) ON CONFLICT (warehouse_id) DO NOTHING",
            wh_rows,
        )
        for wh in canonical["warehouses"]:
            cur.execute(
                "INSERT INTO warehouses (warehouse_id, capacity_class, region) VALUES (%s, %s, %s) "
                "ON CONFLICT (warehouse_id) DO NOTHING",
                (wh["warehouse_id"], DEFAULT_CAPACITY_CLASS, wh["region"]),
            )

        aggregated = _aggregate_lots(dataset["inventory_lots"], parts_local)
        cur.executemany(
            "INSERT INTO inventory_lots (lot_id, part, warehouse_id, on_hand, reserved, quality_status) "
            "VALUES (%(lot_id)s, %(part)s, %(warehouse_id)s, %(on_hand)s, %(reserved)s, %(quality_status)s) "
            "ON CONFLICT (lot_id) DO NOTHING",
            aggregated,
        )

        cp = canonical["part"]
        for lot in canonical["inventory_lots"]:
            cur.execute(
                "INSERT INTO inventory_lots (lot_id, part, warehouse_id, on_hand, reserved, quality_status) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (lot_id) DO NOTHING",
                (
                    lot["lot_id"],
                    cp["source_identity_map"]["WMS"],
                    lot["warehouse"],
                    lot["on_hand"],
                    lot["reserved"],
                    lot["quality_status"],
                ),
            )
    conn.commit()
