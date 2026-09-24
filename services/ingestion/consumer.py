#!/usr/bin/env python3
"""Kafka consumer of Debezium's CDC topics -> identity resolve -> RDF4J
(phase3.md item 5). Runs as a docker-compose service (services/ingestion in
docker-compose.yml, image = the shared root Dockerfile, command override).

Failure handling:
- RDF4J unreachable / 5xx / 404 (repo not bootstrapped yet — a real startup
  race against `make up`'s bootstrap_rdf4j.py step) -> RDF4JUnavailable:
  retry the SAME message with exponential backoff, never commit its offset
  -> "stopping RDF4J makes ingestion back off without data loss, and it
  resumes after restart" (phase3.md item 7).
- Malformed/unmappable message (bad JSON, missing required field, a
  genuine SHACL rejection of the mapped triples) -> PoisonMessage: routed
  to the oo.ingestion.dlq topic, counted, offset committed so one bad
  message can never wedge the pipeline (F38).
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import httpx
from confluent_kafka import Consumer, Producer

from services.common.rdf4j_client import RDF4JClient
from services.identity_resolver.resolver import IdentityResolver, Quarantined
from services.ingestion import health, mapping, store

TOPIC_PREFIX = {"erp": "oo.erp", "mes": "oo.mes", "wms": "oo.wms"}
TABLES = {
    "erp": ["suppliers", "parts", "purchase_orders", "purchase_order_lines"],
    "mes": ["production_lines", "work_orders", "bom_requirements"],
    # Phase 6 (docs/experiment/implementation-notes.md Phase 5 section's own
    # handoff note): `transfers` is now mapped (services/ingestion/mapping.py
    # -> fac:WmsTransferRecord) — the wms-connector's table.include.list
    # already captured it since Phase 2/3 (contracts/cdc/v1/wms-connector.json),
    # this consumer just never subscribed to/consumed it before. Adding it
    # here is also what makes services/ingestion/readiness.py's
    # wait_for_zero_kafka_lag cover it correctly (previously excluded by
    # name specifically to avoid a permanent phantom lag on an unconsumed
    # topic — see that module's own comment, now stale in spirit but
    # harmless: all_topics() is derived from THIS dict, not hand-maintained
    # twice).
    "wms": ["warehouses", "inventory_lots", "transfers"],
}
DLQ_TOPIC = "oo.ingestion.dlq"

# Phase 5 fix (watermark-based evidence freshness): Debezium's
# `heartbeat.interval.ms` (contracts/cdc/v1/*-connector.json, now 1000ms)
# was ALREADY configured since Phase 3 but nothing ever consumed the
# heartbeat topics it produces — verified empirically that they exist and
# carry a fresh `{"ts_ms": ...}` message every second even on a completely
# idle source database (`__debezium-heartbeat.<topic.prefix>`, confirmed via
# `kafka-console-consumer` against a live idle stack). These are subscribed
# to SEPARATELY from `all_topics()` (which services/ingestion/readiness.py's
# `wait_for_zero_kafka_lag` also uses for its own convergence gate) —
# heartbeats arrive every ~1s, so folding them into that SAME lag
# calculation would make "stable zero lag across 2 samples" flaky by
# construction. `run()` subscribes to `all_topics() + heartbeat_topics()`
# together (one consumer, one Kafka group), but readiness.py's lag check
# stays scoped to `all_topics()` only.
HEARTBEAT_TOPIC_PREFIX = "__debezium-heartbeat."


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
    """Non-retryable: routed to the DLQ, offset committed, pipeline continues."""


class RDF4JUnavailable(Exception):
    """Retryable: same message retried with backoff, offset NOT committed."""


def parse_topic(topic: str) -> tuple[str, str]:
    # "oo.<system>.public.<table>" per contracts/cdc/v1/*.json's topic.prefix.
    parts = topic.split(".")
    if len(parts) != 4 or parts[0] != "oo" or parts[2] != "public":
        raise ValueError(f"unexpected topic name shape: {topic!r}")
    return parts[1], parts[3]


def process_message(msg, resolver: IdentityResolver, ing_store: store.IngestionStore, state: health.HealthState) -> None:
    system, table = parse_topic(msg.topic())

    raw_value = msg.value()
    if raw_value is None:
        return  # tombstone (shouldn't occur — tombstones.on.delete=false — but harmless if it does)

    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as e:
        raise PoisonMessage(f"invalid JSON in {msg.topic()}: {e}") from e

    op = payload.get("op")
    if op is None:
        raise PoisonMessage(f"{msg.topic()}: missing 'op' in CDC envelope")

    source = payload.get("source") or {}
    source_lsn = source.get("lsn")
    after = payload.get("after")
    before = payload.get("before")

    spec = mapping.TABLE_SPECS.get((system, table))
    if spec is None:
        return  # a table we deliberately don't map (e.g. wms.transfers) — not poison.

    row_for_pk = after if after is not None else before
    if row_for_pk is None:
        raise PoisonMessage(f"{msg.topic()}: both before and after are null")

    pk_col = "part_id" if (table == "parts" and system == "erp") else spec.pk_column
    pk_value = row_for_pk.get(pk_col)
    if pk_value is None:
        raise PoisonMessage(f"{msg.topic()}: row missing primary key column {pk_col!r}")
    source_version = row_for_pk.get("version")

    entity_iri = mapping.resolve_entity_iri(system, table, str(pk_value), resolver)

    mapped = None
    if op != "d":
        mapped = mapping.map_row(system, table, after, resolver)

    try:
        result = ing_store.apply_event(system, table, str(pk_value), op, entity_iri, mapped, source_lsn, source_version)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 409:
            raise PoisonMessage(f"{msg.topic()}: RDF4J rejected write (SHACL violation, HTTP 409): {e}") from e
        if status >= 500 or status == 404:
            raise RDF4JUnavailable(f"{msg.topic()}: RDF4J HTTP {status}") from e
        raise PoisonMessage(f"{msg.topic()}: RDF4J HTTP {status}: {e}") from e
    except httpx.TransportError as e:
        # Broadened from (httpx.ConnectError, httpx.TimeoutException) after a
        # real Phase 5 finding: `docker compose stop rdf4j` mid-request can
        # make the TCP connection accept but then close before a response is
        # sent, raising httpx.RemoteProtocolError ("Server disconnected
        # without sending a response") — a THIRD distinct transport failure
        # neither ConnectError nor TimeoutException covers. Uncaught, this
        # exception propagated out of the consumer's main loop and crashed
        # the whole `ingestion` container (verified: `docker compose ps`
        # showed `Exited (1)`, permanently starving every hot-projection
        # test downstream until manually restarted). httpx.ConnectError,
        # httpx.TimeoutException, and httpx.RemoteProtocolError are ALL
        # httpx.TransportError subclasses — catching the base class is both
        # simpler and closes this whole class of "some other transport-level
        # hiccup" failure mode, not just the two specific ones enumerated by
        # hand.
        raise RDF4JUnavailable(f"{msg.topic()}: {e}") from e

    if result["applied"]:
        state.incr("messages_applied")
        if mapped is not None and isinstance(mapped.identity_result, Quarantined):
            state.incr("messages_quarantined_identity")
    else:
        state.incr("messages_skipped_stale_or_duplicate")


def send_to_dlq(producer: Producer, msg, error: str) -> None:
    dlq_payload = {
        "original_topic": msg.topic(),
        "original_partition": msg.partition(),
        "original_offset": msg.offset(),
        "key": msg.key().decode("utf-8", errors="replace") if msg.key() else None,
        "value": msg.value().decode("utf-8", errors="replace") if msg.value() else None,
        "error": error,
        "quarantined_at": datetime.now(timezone.utc).isoformat(),
    }
    producer.produce(DLQ_TOPIC, value=json.dumps(dlq_payload).encode("utf-8"))
    producer.flush(5.0)


def run(consumer: Consumer, producer: Producer, resolver: IdentityResolver, ing_store: store.IngestionStore, state: health.HealthState) -> None:
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
            # A heartbeat message needs no CDC processing at all — its mere
            # arrival IS the fact being recorded: "the Debezium connector
            # for this system is alive and there is nothing new to report as
            # of now" (docs/experiment/spec/04_architecture.md consistency
            # model). Committing its offset only tracks this consumer
            # group's own position in that topic; it has no bearing on data
            # correctness (unlike a real CDC topic's offset).
            state.touch_watermark(heartbeat_system, datetime.now(timezone.utc).isoformat())
            consumer.commit(msg)
            continue

        state.incr("messages_consumed")
        while True:
            try:
                process_message(msg, resolver, ing_store, state)
                consumer.commit(msg)
                system, _table = parse_topic(msg.topic())
                state.touch_watermark(system, datetime.now(timezone.utc).isoformat())
                backoff = 1.0
                state.set_error(None)  # clear a stale error once processing recovers
                break
            except PoisonMessage as e:
                state.set_error(str(e))
                send_to_dlq(producer, msg, str(e))
                state.incr("poison_messages")
                consumer.commit(msg)
                # A poison message still PROVES the connector/topic itself is
                # being drained live (the failure is in OUR mapping/SHACL,
                # not source connectivity) — touch the watermark so one bad
                # row doesn't manufacture a false staleness verdict for
                # every other fact from the same source.
                system, _table = parse_topic(msg.topic())
                state.touch_watermark(system, datetime.now(timezone.utc).isoformat())
                break
            except RDF4JUnavailable as e:
                state.set_error(str(e))
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                continue  # retry same message; offset never committed -> no data loss


def main() -> int:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:15492")
    rdf4j_base = os.environ.get("RDF4J_BASE_URL", "http://localhost:15480/rdf4j-server")
    rdf4j_repo = os.environ.get("RDF4J_REPOSITORY", "oo")
    health_port = int(os.environ.get("OO_INGESTION_HEALTH_PORT", "8090"))

    state = health.HealthState()
    health.start_health_server(state, health_port)

    client = RDF4JClient(base_url=rdf4j_base, repository=rdf4j_repo)
    resolver = IdentityResolver()
    ing_store = store.IngestionStore(client)

    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": "oo-ingestion",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    producer = Producer({"bootstrap.servers": bootstrap})

    try:
        run(consumer, producer, resolver, ing_store, state)
    finally:
        consumer.close()
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
