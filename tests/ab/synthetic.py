"""Synthetic scenario seeding for the A/B workloads (Phase 8, spec 10) —
NEVER touches the canonical fixture (PX-17/SKU-88429/WH-A/WH-B/WO-42;
common.md: "Use SYNTHETIC SKUs/warehouses in any new test or probe").

Parts use the SAME `contracts/identity/v1/mapping_rules.yaml`
generated-index-v1 pattern the real seed dataset uses (PART-{i:05d} /
COMP-{i:05d} / SKU-{100000+i} -> canonical PX-{i:04d}), from a RESERVED
index range (7000-8999) the real seed generator never touches (0-499) and
the explicit-override fixtures never claim (PX-17, PX-0007) — so identity
resolution works through the REAL resolver code in both variants, no
special-casing.

Work orders / purchase orders are plain unique ids in their own
`*-AB-*` namespace (only `part` fields need identity resolution — work
order / PO ids are already canonical, per services/identity_resolver's own
module docstring), reusing an EXISTING supplier (S-0) and production line
(LINE-00) for their FK requirements rather than inserting new parent rows.

Every insert goes through the SAME path `seed/load.py` uses (a direct SQL
insert into the SOURCE system's own database, via that system's own role
credentials) — never a shortcut into ontology_hot or baseline directly —
so the SAME real Debezium CDC pipeline propagates it to BOTH variants
(fairness rule 3: "same external source behavior").
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import psycopg

from seed import db_env

# Reserved synthetic index range — never used by seed/generators/generate.py
# (0..499) or the explicit-override fixtures (PX-17, PX-0007).
_INDEX_START = 7000


@dataclass(frozen=True)
class SyntheticPart:
    index: int
    erp_id: str
    mes_id: str
    wms_id: str
    canonical_id: str


def part_ids(index: int) -> SyntheticPart:
    i = _INDEX_START + index
    return SyntheticPart(
        index=i,
        erp_id=f"PART-{i:05d}",
        mes_id=f"COMP-{i:05d}",
        wms_id=f"SKU-{100000 + i}",
        canonical_id=f"PX-{i:04d}",
    )


def ensure_erp_part(conn: psycopg.Connection, part: SyntheticPart, criticality: str = "MEDIUM") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO parts (part_id, description, unit, criticality)
            VALUES (%s, %s, 'EA', %s)
            ON CONFLICT (part_id) DO UPDATE SET criticality = EXCLUDED.criticality, version = parts.version + 1, updated_at = now()
            """,
            (part.erp_id, f"synthetic A/B test part {part.index}", criticality),
        )
    conn.commit()


def set_wms_inventory(base_url: str, part: SyntheticPart, warehouse_id: str, on_hand: int, reserved: int = 0, quality_status: str = "OK") -> dict:
    """Goes through the REAL WMS test-mode endpoint (same one
    tests/integration/decision_helpers.py::set_inventory_and_wait uses) —
    a real write to WMS's own database, observed by CDC exactly like any
    other WMS mutation, never a direct write into a projection/replica."""
    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        r = client.post(
            "/_test/inventory/set",
            json={"part": part.wms_id, "warehouse_id": warehouse_id, "on_hand": on_hand, "reserved": reserved, "quality_status": quality_status},
        )
        r.raise_for_status()
        return r.json()


def insert_work_order(
    conn: psycopg.Connection, work_order_id: str, warehouse: str, status: str, priority: str,
    planned_start: int, planned_finish: int = 1000, production_line_id: str = "LINE-00",
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO work_orders (work_order_id, production_line_id, status, priority, planned_start, planned_finish, warehouse)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (work_order_id) DO UPDATE SET status = EXCLUDED.status, priority = EXCLUDED.priority,
                planned_start = EXCLUDED.planned_start, warehouse = EXCLUDED.warehouse, version = work_orders.version + 1, updated_at = now()
            """,
            (work_order_id, production_line_id, status, priority, planned_start, planned_finish, warehouse),
        )
    conn.commit()


def insert_bom_requirement(conn: psycopg.Connection, work_order_id: str, part: SyntheticPart, qty: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO bom_requirements (work_order_id, part_id, qty) VALUES (%s, %s, %s) RETURNING id",
            (work_order_id, part.mes_id, qty),
        )
        req_id = cur.fetchone()[0]
    conn.commit()
    return req_id


def insert_purchase_order(conn: psycopg.Connection, po_id: str, status: str, promised_at: int, expected_at: int, supplier_id: str = "SUP-0000") -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO purchase_orders (po_id, supplier_id, status, promised_at, expected_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (po_id) DO UPDATE SET status = EXCLUDED.status, expected_at = EXCLUDED.expected_at, version = purchase_orders.version + 1, updated_at = now()
            """,
            (po_id, supplier_id, status, promised_at, expected_at),
        )
    conn.commit()


def insert_purchase_order_line(conn: psycopg.Connection, po_id: str, part: SyntheticPart, qty: int, destination_warehouse: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO purchase_order_lines (po_id, part_id, qty, destination_warehouse) VALUES (%s, %s, %s, %s)",
            (po_id, part.erp_id, qty, destination_warehouse),
        )
    conn.commit()


# --- Convergence waiting: both variants must have caught up before an
# evidence-sensitive measurement is taken (see docs/experiment/implementation-notes.md
# Phase 8 item 1's "Operational note" section) ------------------------------

def wait_baseline_inventory(conn: psycopg.Connection, part: SyntheticPart, warehouse_id: str, expect_on_hand: int, timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with conn.cursor() as cur:
            cur.execute("SELECT on_hand FROM inventory_lots WHERE part = %s AND warehouse_id = %s", (part.canonical_id, warehouse_id))
            row = cur.fetchone()
        if row is not None and row[0] == expect_on_hand:
            return True
        time.sleep(0.5)
    return False


def wait_ontology_inventory(ontology_hot_conn: psycopg.Connection, part: SyntheticPart, warehouse_id: str, expect_on_hand: int, timeout_s: float = 30.0) -> bool:
    """Polls the SAME `current_inventory` HOT PROJECTION table
    services/decision_service/evidence.py actually reads (never raw RDF4J
    facts, which can be visible slightly before the projection_builder's
    own poll cycle — ~3s — has rebuilt from them; polling the wrong layer
    here made an earlier version of this helper report "converged" while
    the real evidence gate still saw a stale/absent row).

    A single fresh-enough read is sufficient (does NOT require sustained
    stability): `current_inventory.computed_at` is rewritten on EVERY
    projection_builder poll cycle (~3s) even when the value doesn't
    change, so requiring N continuous seconds of freshness fights that
    cycle instead of using it — and evidence.py's OWN internal retry
    (`_resolve_source_inventory_with_freshness`, up to 8s/10 attempts)
    already absorbs the remaining race between "this helper observed a
    fresh row" and "propose() re-observes it a moment later"."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with ontology_hot_conn.cursor() as cur:
            cur.execute(
                "SELECT on_hand, now() - computed_at FROM current_inventory WHERE part = %s AND warehouse = %s",
                (part.canonical_id, warehouse_id),
            )
            row = cur.fetchone()
        if row is not None and row[0] == expect_on_hand and row[1].total_seconds() < 5.0:
            return True
        time.sleep(0.5)
    return False


def wait_both_converged(conn_baseline: psycopg.Connection, ontology_hot_conn: psycopg.Connection, part: SyntheticPart, warehouse_id: str, expect_on_hand: int, timeout_s: float = 40.0) -> dict[str, bool]:
    deadline = time.monotonic() + timeout_s
    baseline_ok = wait_baseline_inventory(conn_baseline, part, warehouse_id, expect_on_hand, timeout_s=timeout_s)
    remaining = max(1.0, deadline - time.monotonic())
    ontology_ok = wait_ontology_inventory(ontology_hot_conn, part, warehouse_id, expect_on_hand, timeout_s=remaining)
    return {"baseline": baseline_ok, "ontology": ontology_ok}
