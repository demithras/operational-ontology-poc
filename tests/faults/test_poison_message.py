"""F38 (docs/experiment/spec/09_failure_and_adversarial_matrix.md "event
poison message -> ingestion -> DLQ/quarantine; pipeline health visible; the
rest continues").

Produces a genuinely malformed message (invalid JSON) directly onto a real
CDC topic (`oo.wms.public.warehouses`) — services/ingestion/consumer.py's
`process_message` raises `PoisonMessage` on `json.JSONDecodeError`, routes
it to `oo.ingestion.dlq` (`send_to_dlq`), commits its offset (never wedging
the topic), and increments `poison_messages` — all real, live behavior of
the running `ingestion` container, not a direct call into its Python
functions.
"""

from __future__ import annotations

import json
import time
import uuid

import httpx

from seed import db_env
from tests.integration.decision_helpers import set_inventory_and_wait

TOPIC = "oo.wms.public.warehouses"
DLQ_TOPIC = "oo.ingestion.dlq"


def _ingestion_health() -> dict:
    return httpx.get(f"{db_env.ingestion_health_url()}/health", timeout=5.0).json()


def test_f38_poison_message_goes_to_dlq_pipeline_health_visible_rest_continues(
    wms_client: httpx.Client, ontology_hot_conn, ingestion_client: httpx.Client
):
    from confluent_kafka import Consumer, Producer

    bootstrap = db_env.kafka_bootstrap_servers()
    before = _ingestion_health()
    before_poison = before["poison_messages"]

    marker = uuid.uuid4().hex[:12]
    producer = Producer({"bootstrap.servers": bootstrap})
    poison_key = f"poison-marker-{marker}".encode("utf-8")
    producer.produce(TOPIC, key=poison_key, value=b"{this is not valid json, marker=" + marker.encode() + b"")
    producer.flush(10.0)

    # 1. Pipeline health stays VISIBLE and honest: the poison_messages
    # counter increments and the pipeline never reports itself unhealthy —
    # F38's "pipeline health visible" (services/ingestion/health.py's
    # /health endpoint keeps answering throughout, no crash/restart).
    deadline = time.monotonic() + 30.0
    poison_after = before_poison
    while time.monotonic() < deadline:
        health = _ingestion_health()
        poison_after = health["poison_messages"]
        if poison_after > before_poison:
            break
        time.sleep(1.0)
    assert poison_after > before_poison, f"poison_messages never incremented (before={before_poison}, after={poison_after})"
    assert health["status"] == "ok"

    # 2. A real DLQ record lands on oo.ingestion.dlq, correlated to the
    # exact poisoned message via our marker (never trusting "some poison
    # message or other arrived" — this could be a different test's).
    # `poison_messages` already incremented above, i.e. ingestion has
    # ALREADY produced the DLQ record by this point — so a fresh consumer
    # group reading from the topic's BEGINNING (never `latest`, which races
    # a not-yet-existing/auto-created topic's partition assignment) is safe
    # and deterministic; it just has to scan past whatever earlier tests
    # left on this shared topic to find OUR marker.
    dlq_consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"oo-f38-dlq-probe-{marker}",
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    dlq_consumer.subscribe([DLQ_TOPIC])
    found_dlq_record: dict | None = None
    deadline = time.monotonic() + 30.0
    scanned = 0
    while time.monotonic() < deadline and found_dlq_record is None:
        msg = dlq_consumer.poll(1.0)
        if msg is None or msg.error():
            continue
        scanned += 1
        try:
            payload = json.loads(msg.value())
        except (ValueError, TypeError):
            continue
        if payload.get("original_topic") == TOPIC and marker in (payload.get("value") or ""):
            found_dlq_record = payload
    dlq_consumer.close()
    assert found_dlq_record is not None, (
        f"no matching record observed on {DLQ_TOPIC} for this test's poisoned message (scanned {scanned} DLQ records)"
    )
    assert "error" in found_dlq_record and found_dlq_record["error"]

    # 3. The rest of the pipeline continues — a normal, well-formed WMS
    # write made AFTER the poison message still converges through CDC
    # exactly as any other test's does (never wedged by the earlier
    # failure — services/ingestion/consumer.py commits the poisoned
    # message's own offset unconditionally).
    set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-910903", "WH-B", on_hand=123)
