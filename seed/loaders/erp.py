"""Loads the generated dataset + canonical incident fixture into the ERP
database. See seed/identity.py for the part-id collision policy."""

from __future__ import annotations

from typing import Any

import psycopg

# Design choice (not specified by docs/experiment/spec/03_domain_scenario.md,
# which only names supplier S-7 in the delay event): fixed attributes for
# the canonical incident's supplier row.
CANONICAL_SUPPLIER_DEFAULTS = {"status": "ACTIVE", "lead_time_days": 10, "risk_class": "HIGH"}


def load(conn: psycopg.Connection, dataset: dict[str, Any], canonical: dict[str, Any], parts_local: dict[str, dict[str, str | None]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO suppliers (supplier_id, name, status, lead_time_days, risk_class) "
            "VALUES (%(supplier_id)s, %(name)s, %(status)s, %(lead_time_days)s, %(risk_class)s) "
            "ON CONFLICT (supplier_id) DO NOTHING",
            dataset["suppliers"],
        )
        supplier_id = canonical["event"]["supplier"]
        cur.execute(
            "INSERT INTO suppliers (supplier_id, name, status, lead_time_days, risk_class) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (supplier_id) DO NOTHING",
            (
                supplier_id,
                f"Supplier {supplier_id}",
                CANONICAL_SUPPLIER_DEFAULTS["status"],
                CANONICAL_SUPPLIER_DEFAULTS["lead_time_days"],
                CANONICAL_SUPPLIER_DEFAULTS["risk_class"],
            ),
        )

        part_rows = [
            {
                "part_id": local["ERP"],
                "description": p["description"],
                "unit": p["unit"],
                "criticality": p["criticality"],
            }
            for p, local in zip(dataset["parts"], (parts_local[p["canonical_part_id"]] for p in dataset["parts"]))
            if local["ERP"] is not None
        ]
        cur.executemany(
            "INSERT INTO parts (part_id, description, unit, criticality) "
            "VALUES (%(part_id)s, %(description)s, %(unit)s, %(criticality)s) ON CONFLICT (part_id) DO NOTHING",
            part_rows,
        )
        cp = canonical["part"]
        cur.execute(
            "INSERT INTO parts (part_id, description, unit, criticality) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (part_id) DO NOTHING",
            (cp["source_identity_map"]["ERP"], cp["description"], cp["unit"], cp["criticality"]),
        )

        cur.executemany(
            "INSERT INTO purchase_orders (po_id, supplier_id, status, promised_at, expected_at) "
            "VALUES (%(po_id)s, %(supplier_id)s, %(status)s, %(promised_at)s, %(expected_at)s) "
            "ON CONFLICT (po_id) DO NOTHING",
            dataset["purchase_orders"],
        )
        canon_po = canonical["purchase_orders"][0]
        cur.execute(
            "INSERT INTO purchase_orders (po_id, supplier_id, status, promised_at, expected_at) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (po_id) DO NOTHING",
            (canon_po["po_id"], supplier_id, canon_po["status"], canon_po["expected_at"], canon_po["expected_at"]),
        )

        line_rows = []
        for po in dataset["purchase_orders"]:
            for line in po["lines"]:
                erp_part = parts_local[line["part"]]["ERP"]
                if erp_part is None:
                    continue  # dropped: this generated part's ERP id collides with the canonical fixture
                line_rows.append(
                    {
                        "po_id": po["po_id"],
                        "part_id": erp_part,
                        "qty": line["qty"],
                        "destination_warehouse": line["destination_warehouse"],
                    }
                )
        cur.executemany(
            "INSERT INTO purchase_order_lines (po_id, part_id, qty, destination_warehouse) "
            "VALUES (%(po_id)s, %(part_id)s, %(qty)s, %(destination_warehouse)s)",
            line_rows,
        )
        cur.execute(
            "INSERT INTO purchase_order_lines (po_id, part_id, qty, destination_warehouse) VALUES (%s, %s, %s, %s)",
            (canon_po["po_id"], cp["source_identity_map"]["ERP"], canon_po["qty"], canon_po["destination_warehouse"]),
        )
    conn.commit()
