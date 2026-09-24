#!/usr/bin/env python3
"""Kafka consumer of Debezium's CDC topics -> identity resolve -> plain
relational upsert (Phase 8, spec 10 Variant A: "fed by the SAME Debezium
CDC topics (its own consumer)"). Same topic set, same envelope parsing, and
the SAME services/identity_resolver.IdentityResolver as
services/ingestion/consumer.py — a SEPARATE consumer group
("oo-baseline", services/baseline/config.BASELINE_KAFKA_CONSUMER_GROUP) so
this variant reads the topics completely independently (its own offsets,
its own backlog if it falls behind), never sharing state with the ontology
variant's `oo-ingestion` group. Subscribes to a SUBSET of the ontology
variant's table list — only the tables this variant's evidence gathering
(services/baseline/evidence.py) actually reads (no `suppliers`/`parts`/
`production_lines` — those never feed a gate decision here, see
evidence.py's own docstring).

Failure handling mirrors services/ingestion/consumer.py exactly (same
class names, same retry-vs-DLQ split) — Postgres-unreachable retries with
backoff and never commits; a malformed/unmappable message goes to the
`oo.ingestion.dlq` topic (the SAME dead-letter topic the ontology variant
uses — no reason for two, since both consumers report the same underlying
"this CDC event could not be applied" fact) and its offset is committed so
one bad message can never wedge this pipeline either.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg  # noqa: E402
from confluent_kafka import Consumer, Producer  # noqa: E402

from services.baseline import identity  # noqa: E402
from services.baseline.config import BASELINE_KAFKA_CONSUMER_GROUP  # noqa: E402
from services.common.db import get_conn, open_pool  # noqa: E402
from services.ingestion import health  # noqa: E402
from services.identity_resolver.resolver import IdentityResolver  # noqa: E402

TOPIC_PREFIX = {"erp": "oo.erp", "mes": "oo.mes", "wms": "oo.wms"}
TABLES = {
    "erp": ["purchase_orders", "purchase_order_lines"],
    "mes": ["work_orders", "bom_requirements"],
    "wms": ["warehouses", "inventory_lots", "transfers"],
}
DLQ_TOPIC = "oo.ingestion.dlq"
HEARTBEAT_TOPIC_PREFIX = "__debezium-heartbeat."

# (system, table) -> (pk_column, part-bearing column name or None)
_PART_COLUMN = {
    ("wms", "inventory_lots"): "part",
    ("wms", "transfers"): "part",
    ("mes", "bom_requirements"): "part_id",
    ("erp", "purchase_order_lines"): "part_id",
}
_PK_COLUMN = {
    ("wms", "warehouses"): "warehouse_id",
    ("wms", "inventory_lots"): "lot_id",
    ("wms", "transfers"): "action_execution_id",
    ("mes", "work_orders"): "work_order_id",
    ("mes", "bom_requirements"): "id",
    ("erp", "purchase_orders"): "po_id",
    ("erp", "purchase_order_lines"): "id",
}


def all_topics() -> list[str]:
    return [f"{TOPIC_PREFIX[system]}.public.{table}" for system, tables in TABLES.items() for table in tables]


def heartbeat_topics() -> list[str]:
    return [f"{HEARTBEAT_TOPIC_PREFIX}{prefix}" for prefix in TOPIC_PREFIX.values()]


def system_from_heartbeat_topic(topic: str) -> str | None:
    if not topic.startswith(HEARTBEAT_TOPIC_PREFIX):
        return None
    prefix = topic[len(HEARTBEAT_TOPIC_PREFIX):]
    for system, topic_prefix in TOPIC_PREFIX.items():
        if topic_prefix == prefix:
            return system
    return None


class PoisonMessage(Exception):
    pass


class DBUnavailable(Exception):
    pass


def parse_topic(topic: str) -> tuple[str, str]:
    parts = topic.split(".")
    if len(parts) != 4 or parts[0] != "oo" or parts[2] != "public":
        raise ValueError(f"unexpected topic name shape: {topic!r}")
    return parts[1], parts[3]


def _resolve_part(conn: psycopg.Connection, resolver: IdentityResolver, system: str, local_part_id: str) -> str | None:
    """Forward-resolves + persists (services/baseline/identity.py), returns
    the canonical id, or None if quarantined (F09 — caller must not invent
    a canonical id for an unresolved local one)."""
    result = identity.resolve_and_store(conn, system.upper(), local_part_id)
    return result.canonical_id if hasattr(result, "canonical_id") else None


def apply_event(conn: psycopg.Connection, resolver: IdentityResolver, system: str, table: str, op: str, after: dict | None, before: dict | None, source_version) -> bool:
    """Returns True if applied, False if skipped (stale/duplicate). Raises
    PoisonMessage for anything structurally wrong."""
    pk_col = _PK_COLUMN.get((system, table))
    if pk_col is None:
        return False  # table we deliberately don't map

    row = after if after is not None else before
    if row is None:
        raise PoisonMessage(f"{system}.{table}: both before and after are null")
    pk_raw = row.get(pk_col)
    if pk_raw is None:
        raise PoisonMessage(f"{system}.{table}: row missing primary key column {pk_col!r}")
    pk = str(pk_raw)

    part_col = _PART_COLUMN.get((system, table))
    canonical_part = None
    if part_col and op != "d" and after is not None:
        local_part = after.get(part_col)
        if local_part is not None:
            canonical_part = _resolve_part(conn, resolver, system, str(local_part))
            if canonical_part is None:
                # Quarantined (F09): recorded above, never guessed — the
                # row itself is still applied (it may still be needed for
                # OTHER fields/joins), just without a usable `part` value,
                # exactly mirroring the ontology variant's
                # oo:Quarantined-instead-of-fac:part treatment.
                pass

    if op == "d":
        table_name = {"warehouses": "warehouses", "inventory_lots": "inventory_lots", "transfers": "wms_transfer_records",
                       "work_orders": "work_orders", "bom_requirements": "bom_requirements",
                       "purchase_orders": "purchase_orders", "purchase_order_lines": "purchase_order_lines"}[table]
        pk_col_baseline = {"warehouses": "warehouse_id", "inventory_lots": "lot_id", "transfers": "action_execution_id",
                            "work_orders": "work_order_id", "bom_requirements": "req_id",
                            "purchase_orders": "po_id", "purchase_order_lines": "line_id"}[table]
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {table_name} WHERE {pk_col_baseline} = %s", (pk,))  # noqa: S608 - fixed internal table/column map
        conn.commit()
        return True

    if system == "wms" and table == "warehouses":
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO warehouses (warehouse_id, capacity_class, region, source_version, cdc_applied_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (warehouse_id) DO UPDATE SET capacity_class = EXCLUDED.capacity_class,
                    region = EXCLUDED.region, source_version = EXCLUDED.source_version, cdc_applied_at = now()
                WHERE warehouses.source_version IS NULL OR EXCLUDED.source_version IS NULL OR EXCLUDED.source_version >= warehouses.source_version
                """,
                (pk, after.get("capacity_class"), after.get("region"), source_version),
            )
            applied = cur.rowcount > 0
    elif system == "wms" and table == "inventory_lots":
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inventory_lots (lot_id, part, warehouse_id, on_hand, reserved, quality_status, source_version, cdc_applied_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (lot_id) DO UPDATE SET part = EXCLUDED.part, warehouse_id = EXCLUDED.warehouse_id,
                    on_hand = EXCLUDED.on_hand, reserved = EXCLUDED.reserved, quality_status = EXCLUDED.quality_status,
                    source_version = EXCLUDED.source_version, cdc_applied_at = now()
                WHERE inventory_lots.source_version IS NULL OR EXCLUDED.source_version IS NULL OR EXCLUDED.source_version >= inventory_lots.source_version
                """,
                (pk, canonical_part or after.get(part_col), after.get("warehouse_id"), after.get("on_hand"), after.get("reserved"), after.get("quality_status"), source_version),
            )
            applied = cur.rowcount > 0
    elif system == "wms" and table == "transfers":
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO wms_transfer_records (action_execution_id, status, requested_quantity, actual_quantity, cdc_applied_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (action_execution_id) DO UPDATE SET status = EXCLUDED.status,
                    actual_quantity = EXCLUDED.actual_quantity, cdc_applied_at = now()
                """,
                (pk, after.get("status"), after.get("requested_quantity"), after.get("actual_quantity")),
            )
            applied = True
    elif system == "mes" and table == "work_orders":
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO work_orders (work_order_id, warehouse_id, status, priority, planned_start, source_version, cdc_applied_at)
                VALUES (%s, %s, %s, %s, %s, %s, now())
                ON CONFLICT (work_order_id) DO UPDATE SET warehouse_id = EXCLUDED.warehouse_id, status = EXCLUDED.status,
                    priority = EXCLUDED.priority, planned_start = EXCLUDED.planned_start,
                    source_version = EXCLUDED.source_version, cdc_applied_at = now()
                WHERE work_orders.source_version IS NULL OR EXCLUDED.source_version IS NULL OR EXCLUDED.source_version >= work_orders.source_version
                """,
                (pk, after.get("warehouse"), after.get("status"), after.get("priority"), after.get("planned_start"), source_version),
            )
            applied = cur.rowcount > 0
    elif system == "mes" and table == "bom_requirements":
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO bom_requirements (req_id, work_order_id, part, qty, cdc_applied_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (req_id) DO UPDATE SET work_order_id = EXCLUDED.work_order_id, part = EXCLUDED.part,
                    qty = EXCLUDED.qty, cdc_applied_at = now()
                """,
                (pk, after.get("work_order_id"), canonical_part or after.get(part_col), after.get("qty")),
            )
            applied = True
    elif system == "erp" and table == "purchase_orders":
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO purchase_orders (po_id, supplier_id, status, expected_at, source_version, cdc_applied_at)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (po_id) DO UPDATE SET supplier_id = EXCLUDED.supplier_id, status = EXCLUDED.status,
                    expected_at = EXCLUDED.expected_at, source_version = EXCLUDED.source_version, cdc_applied_at = now()
                WHERE purchase_orders.source_version IS NULL OR EXCLUDED.source_version IS NULL OR EXCLUDED.source_version >= purchase_orders.source_version
                """,
                (pk, after.get("supplier_id"), after.get("status"), after.get("expected_at"), source_version),
            )
            applied = cur.rowcount > 0
    elif system == "erp" and table == "purchase_order_lines":
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO purchase_order_lines (line_id, po_id, part, destination_wh, qty, cdc_applied_at)
                VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (line_id) DO UPDATE SET po_id = EXCLUDED.po_id, part = EXCLUDED.part,
                    destination_wh = EXCLUDED.destination_wh, qty = EXCLUDED.qty, cdc_applied_at = now()
                """,
                (pk, after.get("po_id"), canonical_part or after.get(part_col), after.get("destination_warehouse"), after.get("qty")),
            )
            applied = True
    else:
        return False

    conn.commit()
    return applied


def process_message(msg, resolver: IdentityResolver, conn: psycopg.Connection, state: health.HealthState) -> None:
    system, table = parse_topic(msg.topic())
    raw_value = msg.value()
    if raw_value is None:
        return
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as e:
        raise PoisonMessage(f"invalid JSON in {msg.topic()}: {e}") from e

    op = payload.get("op")
    if op is None:
        raise PoisonMessage(f"{msg.topic()}: missing 'op' in CDC envelope")
    after = payload.get("after")
    before = payload.get("before")
    source = payload.get("source") or {}

    # Bug found live (2026-09-24): `source.get("lsn")` is Postgres's raw WAL
    # log sequence number — a monotonically growing value that routinely
    # exceeds a 32-bit INT range (confirmed empirically: "integer out of
    # range" wedged this consumer on a real inventory_lots update, which
    # ALSO silently stalled every OTHER topic behind it, since retrying the
    # same poisoned-by-a-schema-mismatch message never commits its offset).
    # The row's OWN `version` column (a small per-row optimistic-lock
    # counter, e.g. services/wms/schema.sql's `version INT NOT NULL DEFAULT 1`)
    # is what `source_version`'s out-of-order guard actually needs —
    # matches the ontology variant's OWN distinction between `source_lsn`
    # and `source_version` as two separate fields
    # (services/ingestion/store.py::apply_event's two parameters).
    row_for_version = after if after is not None else before
    row_version = row_for_version.get("version") if row_for_version else None
    try:
        applied = apply_event(conn, resolver, system, table, op, after, before, row_version)
    except psycopg.Error as e:
        conn.rollback()
        raise DBUnavailable(f"{msg.topic()}: {e}") from e

    if applied:
        state.incr("messages_applied")
    else:
        state.incr("messages_skipped_stale_or_duplicate")


def send_to_dlq(producer: Producer, msg, error: str) -> None:
    dlq_payload = {
        "original_topic": msg.topic(), "original_partition": msg.partition(), "original_offset": msg.offset(),
        "key": msg.key().decode("utf-8", errors="replace") if msg.key() else None,
        "value": msg.value().decode("utf-8", errors="replace") if msg.value() else None,
        "error": error, "quarantined_at": datetime.now(timezone.utc).isoformat(), "consumer": "baseline",
    }
    producer.produce(DLQ_TOPIC, value=json.dumps(dlq_payload).encode("utf-8"))
    producer.flush(5.0)


def run(consumer: Consumer, producer: Producer, resolver: IdentityResolver, state: health.HealthState) -> None:
    consumer.subscribe(all_topics() + heartbeat_topics())
    state.set_ready(True)
    backoff = 1.0
    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            state.set_error(str(msg.error()))
            continue

        heartbeat_system = system_from_heartbeat_topic(msg.topic())
        if heartbeat_system is not None:
            _touch_watermark(heartbeat_system)
            state.touch_watermark(heartbeat_system, datetime.now(timezone.utc).isoformat())
            consumer.commit(msg)
            continue

        state.incr("messages_consumed")
        while True:
            try:
                with get_conn() as conn:
                    process_message(msg, resolver, conn, state)
                consumer.commit(msg)
                system, _table = parse_topic(msg.topic())
                _touch_watermark(system)
                state.touch_watermark(system, datetime.now(timezone.utc).isoformat())
                backoff = 1.0
                state.set_error(None)
                break
            except PoisonMessage as e:
                state.set_error(str(e))
                send_to_dlq(producer, msg, str(e))
                state.incr("poison_messages")
                consumer.commit(msg)
                system, _table = parse_topic(msg.topic())
                _touch_watermark(system)
                state.touch_watermark(system, datetime.now(timezone.utc).isoformat())
                break
            except DBUnavailable as e:
                state.set_error(str(e))
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue


def _touch_watermark(system: str) -> None:
    """Baseline's own single-watermark freshness signal (schema.sql's
    `ingestion_watermarks` table — see services/baseline/evidence.py's
    docstring for why this variant needs only one, unlike the ontology
    variant's ingestion-watermark + hot-projection-computed_at pair)."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_watermarks (system, last_applied_at) VALUES (%s, now()) "
                "ON CONFLICT (system) DO UPDATE SET last_applied_at = now()",
                (system,),
            )
        conn.commit()


def main() -> int:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:15492")
    health_port = int(os.environ.get("OO_BASELINE_INGESTION_HEALTH_PORT", "8095"))

    state = health.HealthState()
    health.start_health_server(state, health_port)

    open_pool()
    with get_conn() as conn:
        from services.baseline.store import apply_schema

        apply_schema(conn)

    resolver = IdentityResolver()
    consumer = Consumer({
        "bootstrap.servers": bootstrap, "group.id": BASELINE_KAFKA_CONSUMER_GROUP,
        "enable.auto.commit": False, "auto.offset.reset": "earliest",
    })
    producer = Producer({"bootstrap.servers": bootstrap})

    try:
        run(consumer, producer, resolver, state)
    finally:
        consumer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
