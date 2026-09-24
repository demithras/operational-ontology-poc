"""Single readiness contract for the whole CDC pipeline
(docs/experiment/briefs/phase4fix.md "A single readiness contract").

`make wait-converged` (services/ingestion/wait_converged.py) and
tests/integration/test_cdc_ingestion.py's `_wait_for_ingestion_caught_up()`
both call this module instead of re-implementing their own partial proxy.

Root cause this replaces (docs/experiment/implementation-notes.md, Phase 4
fix section, has the full empirical write-up): the old
`_wait_for_ingestion_caught_up()` polled the ingestion consumer's own
`messages_consumed` counter and declared success the moment two 2-second
samples were equal. That is satisfied just as happily by "nothing has
arrived at Kafka yet" as by "everything has been drained" — observed
empirically right after `make seed`, before Debezium had read the new WAL
records at all, so `_wait_for_ingestion_caught_up()` returned immediately
and the canonical lot (LOT-A-PX17) was genuinely absent from RDF4J.

This module checks, in order:
  1. every Debezium connector + task is RUNNING (Connect REST API).
  2. the ingestion consumer group's committed offset has caught up to each
     CDC topic's CURRENT high-watermark (real Kafka lag, computed fresh
     each sample — never a stale/cached notion of lag), stable across two
     consecutive samples.
  3. (only when `expect_data=True`, i.e. a seed has actually run) the
     canonical fixture (WO-42, LOT-A-PX17) is present in RDF4J.
  4. (same condition) the work_order_risk hot projection has a WO-42 row.

Steps 3 and 4 are the load-bearing correctness guarantee — they poll the
GROUND TRUTH the tests actually need, with their own generous timeout, so
even if step 2's Kafka-lag snapshot is itself sampled too early (a topic's
high-watermark can lag reality by however long Debezium takes to read a
freshly committed Postgres transaction), steps 3/4 simply keep retrying
until the real data shows up. Step 2 is real defense-in-depth, not the
sole correctness mechanism.

NOTE on a discarded alternative: comparing each replication slot's
`confirmed_flush_lsn` against `pg_current_wal_lsn()` looked like the
"authoritative" way to know Debezium had caught up with Postgres, but
`pg_current_wal_lsn()` is CLUSTER-WIDE — services/projection_builder's own
poll-every-3s TRUNCATE+INSERT cycle against the unrelated `ontology_hot`
database keeps advancing it continuously, so a slot's flush position never
converges to "current" even when the connector has captured 100% of its
own tables' changes. Measured on the stable running stack: ~190MB of
"lag" by that metric while the ingestion health endpoint showed
messages_consumed == messages_applied and zero real backlog. Abandoned in
favor of the ground-truth checks (3) and (4) above.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

import httpx
import psycopg
from confluent_kafka import Consumer, TopicPartition
from confluent_kafka._model import ConsumerGroupTopicPartitions
from confluent_kafka.admin import AdminClient

from seed import db_env
from services.common.rdf4j_client import RDF4JClient
from services.ingestion.consumer import all_topics as _ingestion_all_topics

INGESTION_GROUP_ID = "oo-ingestion"
CONNECTOR_NAMES = ["oo-poc-erp-connector", "oo-poc-mes-connector", "oo-poc-wms-connector"]
# The exact topic list the ingestion consumer itself subscribes to
# (services/ingestion/consumer.py::all_topics()) — NOT every topic the
# Debezium connectors happen to produce (a hand-maintained topic list
# derived from the connector configs instead of this function was tried
# first and produced a permanent phantom lag on an unconsumed topic —
# caught empirically while validating this module against the live stack).
# `wms.transfers` (Phase 6: consumer.py's TABLES now includes it, mapped to
# fac:WmsTransferRecord) is therefore correctly covered here too, since this
# is derived, never hand-duplicated.
CDC_TOPICS = _ingestion_all_topics()
OBSERVED_GRAPH = "https://example.local/oo/graph/observed"
CANONICAL_WORK_ORDER_SUBJECT = "https://example.local/factory/instance/WorkOrder/WO-42"
CANONICAL_LOT_SUBJECT = "https://example.local/factory/instance/InventoryLot/LOT-A-PX17"
ONHAND_PREDICATE = "https://example.local/factory/onHand"

Logger = Callable[[str], None]


class ConvergenceTimeout(RuntimeError):
    """Raised by every wait_for_* function below on timeout — the message
    always states exactly what was still missing (common.md honesty rule:
    never silently declare success)."""


def _noop(_: str) -> None:
    return None


def _bootstrap_servers() -> str:
    return f"localhost:{os.environ['KAFKA_HOST_PORT']}"


# --- 1. connectors RUNNING -------------------------------------------------


def connectors_running(timeout_s: float = 60.0, log: Logger = _noop) -> None:
    connect_url = db_env.connect_rest_url()
    deadline = time.monotonic() + timeout_s
    problems: list[str] = ["not checked yet"]
    with httpx.Client() as client:
        while time.monotonic() < deadline:
            problems = []
            for name in CONNECTOR_NAMES:
                try:
                    r = client.get(f"{connect_url}/connectors/{name}/status", timeout=5.0)
                    r.raise_for_status()
                    status = r.json()
                except httpx.HTTPError as e:
                    problems.append(f"{name}: unreachable ({e})")
                    continue
                if status["connector"]["state"] != "RUNNING":
                    problems.append(f"{name}: connector state={status['connector']['state']}")
                for task in status.get("tasks", []):
                    if task["state"] != "RUNNING":
                        problems.append(f"{name}: task {task['id']} state={task['state']}")
            if not problems:
                log("[readiness] all connectors + tasks RUNNING")
                return
            time.sleep(2.0)
    raise ConvergenceTimeout(f"connectors not RUNNING after {timeout_s}s: {problems}")


# --- 2. ingestion consumer lag == 0 against CURRENT high-watermarks -------


def _all_topic_partitions(admin: AdminClient) -> list[TopicPartition]:
    metadata = admin.list_topics(timeout=10.0)
    tps: list[TopicPartition] = []
    for topic in CDC_TOPICS:
        info = metadata.topics.get(topic)
        if info is None or info.error is not None:
            continue  # topic doesn't exist yet -> nothing produced -> no lag possible
        for partition_id in info.partitions:
            tps.append(TopicPartition(topic, partition_id))
    return tps


def kafka_lag(bootstrap_servers: str, group_id: str = INGESTION_GROUP_ID) -> dict[str, int]:
    """Per-topic total lag (summed across partitions):
    high_watermark - committed_offset, using FRESH values fetched right
    now — never a cached/previous notion of either."""
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    tps = _all_topic_partitions(admin)
    if not tps:
        return {}

    consumer = Consumer({"bootstrap.servers": bootstrap_servers, "group.id": "oo-readiness-probe"})
    try:
        watermarks = {(tp.topic, tp.partition): consumer.get_watermark_offsets(tp, timeout=10.0, cached=False)[1] for tp in tps}
    finally:
        consumer.close()

    committed: dict[tuple[str, int], int] = {}
    futures = admin.list_consumer_group_offsets([ConsumerGroupTopicPartitions(group_id, tps)])
    for future in futures.values():
        response = future.result(timeout=15.0)
        for tp in response.topic_partitions:
            committed[(tp.topic, tp.partition)] = max(tp.offset, 0)

    lag_by_topic: dict[str, int] = {}
    for tp in tps:
        key = (tp.topic, tp.partition)
        lag_by_topic[tp.topic] = lag_by_topic.get(tp.topic, 0) + max(watermarks.get(key, 0) - committed.get(key, 0), 0)
    return lag_by_topic


def wait_for_zero_kafka_lag(
    bootstrap_servers: str, timeout_s: float = 180.0, stable_samples: int = 2, sample_interval_s: float = 2.0, log: Logger = _noop
) -> None:
    deadline = time.monotonic() + timeout_s
    consecutive_zero = 0
    last_lag: dict[str, int] = {}
    while time.monotonic() < deadline:
        last_lag = kafka_lag(bootstrap_servers)
        total = sum(last_lag.values())
        log(f"[readiness] kafka lag total={total} per-topic={last_lag}")
        if total == 0:
            consecutive_zero += 1
            if consecutive_zero >= stable_samples:
                return
        else:
            consecutive_zero = 0
        time.sleep(sample_interval_s)
    raise ConvergenceTimeout(f"ingestion consumer lag did not reach 0 within {timeout_s}s; last per-topic lag: {last_lag}")


# --- 2.5. ingestion has recorded a watermark for every source system ------
# (Phase 5 fix: watermark-based evidence freshness). A brand-new ingestion
# process has an EMPTY watermarks dict until its first heartbeat/CDC message
# is processed (~1s given contracts/cdc/v1/*-connector.json's
# heartbeat.interval.ms=1000, but a Kafka consumer-group rebalance can push
# this out further) — found empirically: a propose() call issued in that
# narrow window correctly (fail-closed) returns INSUFFICIENT_EVIDENCE, but
# that is not what `make up`/`make seed`/`make reset` should hand back as
# "converged". Zero Kafka lag on the ORDINARY CDC topics (step 2) says
# nothing about the heartbeat topics, which are a separate subscription.


def ingestion_watermarks(ingestion_health_url: str) -> dict[str, str]:
    with httpx.Client(timeout=5.0) as client:
        r = client.get(f"{ingestion_health_url}/health")
    r.raise_for_status()
    return r.json().get("watermarks", {})


def wait_for_ingestion_watermarks(
    ingestion_health_url: str, systems: tuple[str, ...] = ("erp", "mes", "wms"), timeout_s: float = 60.0, poll_interval_s: float = 1.0, log: Logger = _noop
) -> None:
    deadline = time.monotonic() + timeout_s
    last_seen: dict[str, str] = {}
    while time.monotonic() < deadline:
        try:
            last_seen = ingestion_watermarks(ingestion_health_url)
        except httpx.HTTPError as e:
            last_seen = {}
            log(f"[readiness] ingestion health unreachable while waiting for watermarks: {e}")
        if all(system in last_seen for system in systems):
            log(f"[readiness] ingestion watermarks present for all sources: {last_seen}")
            return
        time.sleep(poll_interval_s)
    missing = [s for s in systems if s not in last_seen]
    raise ConvergenceTimeout(f"ingestion watermark missing for {missing} after {timeout_s}s (last seen: {last_seen})")


# --- 2.75. hot-projection `computed_at` is recent -------------------------
# (Phase 5 fix: watermark-based evidence freshness). services/projection_builder
# is an INDEPENDENT poll loop (every ~3s) that reads FROM RDF4J — an RDF4J
# outage (or its own restart) stalls its OWN cycle too, and `_wait_healthy`
# on its bare HTTP endpoint only proves the process is UP, not that its
# NEXT post-recovery build has actually landed. Found empirically: a
# continuous monitor during a full `make test` run showed `computed_at`
# staying frozen for 11-19 REAL seconds after test_cdc_ingestion.py's own
# RDF4J-outage test's `finally` block already considered RDF4J "back"
# (`repository_exists()` returning True) — the gap between "RDF4J answers"
# and "the hot projection has actually caught back up" is exactly what this
# closes, for ANY test that disrupts RDF4J or projection_builder directly.


def wait_for_fresh_hot_projection(dsn: str, max_age_s: float = 5.0, timeout_s: float = 30.0, poll_interval_s: float = 0.5, log: Logger = _noop) -> None:
    import psycopg as _psycopg
    from datetime import datetime, timezone

    deadline = time.monotonic() + timeout_s
    last_age: float | None = None
    while time.monotonic() < deadline:
        try:
            with _psycopg.connect(dsn, connect_timeout=3) as conn, conn.cursor() as cur:
                cur.execute("SELECT max(computed_at) FROM current_inventory")
                row = cur.fetchone()
            if row and row[0] is not None:
                last_age = (datetime.now(timezone.utc) - row[0]).total_seconds()
                if last_age <= max_age_s:
                    log(f"[readiness] hot projection computed_at fresh (age={last_age:.2f}s)")
                    return
        except _psycopg.OperationalError as e:
            log(f"[readiness] ontology_hot not reachable while waiting for fresh computed_at: {e}")
        time.sleep(poll_interval_s)
    raise ConvergenceTimeout(f"hot projection computed_at did not become fresh within {timeout_s}s (last age: {last_age})")


# --- 3. RDF4J contains the canonical fixture -------------------------------


def rdf4j_has_canonical_fixture(rdf4j_client: RDF4JClient) -> tuple[bool, str]:
    wo_exists = rdf4j_client.ask(f"ASK {{ GRAPH <{OBSERVED_GRAPH}> {{ <{CANONICAL_WORK_ORDER_SUBJECT}> a ?t }} }}")
    if not wo_exists:
        return False, f"WO-42 ({CANONICAL_WORK_ORDER_SUBJECT}) not present in RDF4J"
    lot_has_on_hand = rdf4j_client.ask(f"ASK {{ GRAPH <{OBSERVED_GRAPH}> {{ <{CANONICAL_LOT_SUBJECT}> <{ONHAND_PREDICATE}> ?v }} }}")
    if not lot_has_on_hand:
        return False, f"LOT-A-PX17 ({CANONICAL_LOT_SUBJECT}) has no fac:onHand fact in RDF4J"
    return True, ""


def wait_for_rdf4j_canonical_fixture(rdf4j_client: RDF4JClient, timeout_s: float = 180.0, poll_interval_s: float = 2.0, log: Logger = _noop) -> None:
    deadline = time.monotonic() + timeout_s
    reason = "not checked yet"
    while time.monotonic() < deadline:
        ok, reason = rdf4j_has_canonical_fixture(rdf4j_client)
        if ok:
            log("[readiness] canonical fixture (WO-42, LOT-A-PX17) present in RDF4J")
            return
        time.sleep(poll_interval_s)
    raise ConvergenceTimeout(f"RDF4J canonical fixture not present within {timeout_s}s: {reason}")


# --- 4. work_order_risk projection has a WO-42 row -------------------------


def ontology_hot_has_work_order_row(dsn: str, work_order_id: str = "WO-42") -> bool:
    with psycopg.connect(dsn, connect_timeout=3) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM work_order_risk WHERE work_order_id = %s", (work_order_id,))
        return cur.fetchone() is not None


def wait_for_work_order_risk_row(dsn: str, work_order_id: str = "WO-42", timeout_s: float = 90.0, poll_interval_s: float = 2.0, log: Logger = _noop) -> None:
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if ontology_hot_has_work_order_row(dsn, work_order_id):
                log(f"[readiness] work_order_risk has a {work_order_id} row")
                return
            last_error = None
        except psycopg.OperationalError as e:
            last_error = e
        time.sleep(poll_interval_s)
    suffix = f" (last connection error: {last_error})" if last_error else ""
    raise ConvergenceTimeout(f"work_order_risk has no {work_order_id} row within {timeout_s}s{suffix}")


# --- orchestrator -----------------------------------------------------------


def wait_for_converged(expect_data: bool = True, timeout_s: float = 240.0, log: Logger = print) -> None:
    """The single readiness contract `make up` / `make seed` / `make reset`
    end on. `expect_data=False` is for a bare reset/up with no seed yet run
    (source tables are still empty, so the fixture/projection checks would
    never be satisfiable) — connectors-running and zero-lag still apply."""
    db_env.load_dotenv()
    bootstrap_servers = _bootstrap_servers()

    log("[readiness] waiting for Debezium connectors to be RUNNING...")
    connectors_running(timeout_s=60.0, log=log)

    log("[readiness] waiting for ingestion consumer lag to reach 0 against current Kafka high-watermarks...")
    wait_for_zero_kafka_lag(bootstrap_servers, timeout_s=timeout_s, log=log)

    log("[readiness] waiting for ingestion watermarks (Debezium heartbeats) for all sources...")
    wait_for_ingestion_watermarks(db_env.ingestion_health_url(), timeout_s=60.0, log=log)

    if not expect_data:
        log("[readiness] expect_data=False — skipping RDF4J fixture / projection checks (no seed run yet).")
        return

    rdf4j_client = RDF4JClient(base_url=db_env.rdf4j_server_url(), repository="oo")
    try:
        log("[readiness] waiting for canonical fixture (WO-42, LOT-A-PX17) in RDF4J...")
        wait_for_rdf4j_canonical_fixture(rdf4j_client, timeout_s=timeout_s, log=log)
    finally:
        rdf4j_client.close()

    log("[readiness] waiting for work_order_risk WO-42 row in ontology_hot...")
    wait_for_work_order_risk_row(db_env.ontology_hot_dsn(), timeout_s=90.0, log=log)

    log("[readiness] pipeline fully converged.")
