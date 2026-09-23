"""Loads the generated dataset + canonical incident fixture into the MES
database. All part references are translated from canonical ids to
MES-local ids (COMP-xxx) via `parts_local` (seed/identity.py) — MES never
sees a canonical id or an ERP/WMS-local id."""

from __future__ import annotations

import json
from typing import Any

import psycopg

# Design choice: the canonical incident fixture does not assign WO-42 to a
# production line (docs/experiment/spec/03_domain_scenario.md only names the
# work order and its requirement). LINE-00 always exists regardless of seed
# (seed/generators/generate.py generates a fixed 8 lines, LINE-00..LINE-07).
CANONICAL_WO_PRODUCTION_LINE = "LINE-00"
# Design choice: the fixture gives planned_start (18) but not planned_finish;
# mirrors the generator's own start-to-finish gap order of magnitude.
CANONICAL_WO_DURATION = 200


def load(conn: psycopg.Connection, dataset: dict[str, Any], canonical: dict[str, Any], parts_local: dict[str, dict[str, str | None]]) -> None:
    with conn.cursor() as cur:
        line_rows = [
            {
                "line_id": line["line_id"],
                "status": line["status"],
                "capabilities": json.dumps(
                    [parts_local[cid]["MES"] for cid in line["capabilities"] if parts_local[cid]["MES"]]
                ),
            }
            for line in dataset["production_lines"]
        ]
        cur.executemany(
            "INSERT INTO production_lines (line_id, status, capabilities) "
            "VALUES (%(line_id)s, %(status)s, %(capabilities)s) ON CONFLICT (line_id) DO NOTHING",
            line_rows,
        )

        wo_rows = [
            {
                "work_order_id": wo["work_order_id"],
                "production_line_id": wo["production_line"],
                "status": wo["status"],
                "priority": wo["priority"],
                "planned_start": wo["planned_start"],
                "planned_finish": wo["planned_finish"],
                "warehouse": wo["warehouse"],
            }
            for wo in dataset["work_orders"]
        ]
        cur.executemany(
            "INSERT INTO work_orders "
            "(work_order_id, production_line_id, status, priority, planned_start, planned_finish, warehouse) "
            "VALUES (%(work_order_id)s, %(production_line_id)s, %(status)s, %(priority)s, "
            "%(planned_start)s, %(planned_finish)s, %(warehouse)s) ON CONFLICT (work_order_id) DO NOTHING",
            wo_rows,
        )
        canon_wo = canonical["work_orders"][0]
        cur.execute(
            "INSERT INTO work_orders "
            "(work_order_id, production_line_id, status, priority, planned_start, planned_finish, warehouse) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (work_order_id) DO NOTHING",
            (
                canon_wo["work_order_id"],
                CANONICAL_WO_PRODUCTION_LINE,
                canon_wo["status"],
                canon_wo["priority"],
                canon_wo["planned_start"],
                canon_wo["planned_start"] + CANONICAL_WO_DURATION,
                canon_wo["warehouse"],
            ),
        )

        bom_rows = []
        for wo in dataset["work_orders"]:
            for canonical_part_id, qty in wo["requirements"].items():
                mes_part = parts_local[canonical_part_id]["MES"]
                if mes_part is None:
                    continue
                bom_rows.append({"work_order_id": wo["work_order_id"], "part_id": mes_part, "qty": qty})
        cur.executemany(
            "INSERT INTO bom_requirements (work_order_id, part_id, qty) "
            "VALUES (%(work_order_id)s, %(part_id)s, %(qty)s)",
            bom_rows,
        )
        cp = canonical["part"]
        cur.execute(
            "INSERT INTO bom_requirements (work_order_id, part_id, qty) VALUES (%s, %s, %s)",
            (canon_wo["work_order_id"], cp["source_identity_map"]["MES"], canon_wo["requirements"][cp["canonical_id"]]),
        )
    conn.commit()
