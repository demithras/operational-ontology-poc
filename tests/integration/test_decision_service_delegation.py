"""F04 (agent allowed with exact task grant) + revoked-grant-denies-immediately
+ F32 (agent delegation chain recorded, never spoofable) —
docs/experiment/spec/08_test_strategy.md "OpenFGA tests" exercised through
the REAL decision_service HTTP API (contracts/authorization/v1/tests.yaml
proves the same claims at the model level, offline).
"""

from __future__ import annotations

import httpx
import psycopg
import pytest

from seed import db_env
from services.decision_service import authz
from tests.integration.decision_helpers import inventory_unchanged, propose_with_freshness_retry, set_inventory_and_wait


@pytest.fixture()
def openfga_store_id(decision_service_reachable: bool) -> str:
    store_id = authz.resolve_store_id(db_env.openfga_api_url())
    if store_id is None:
        pytest.skip("OpenFGA 'oo-poc' store not bootstrapped — run 'make up' first")
    return store_id


def _write_agent_grant(store_id: str, warehouse: str) -> None:
    r = httpx.post(
        f"{db_env.openfga_api_url()}/stores/{store_id}/write",
        json={"writes": {"tuple_keys": [{"user": "agent:agent-1", "relation": "agent_grant", "object": f"warehouse:{warehouse}"}]}},
        timeout=5.0,
    )
    assert r.status_code in (200, 400), r.text  # 400 tolerated: "already exists" from a prior partial run


def _delete_agent_grant(store_id: str, warehouse: str) -> None:
    r = httpx.post(
        f"{db_env.openfga_api_url()}/stores/{store_id}/write",
        json={"deletes": {"tuple_keys": [{"user": "agent:agent-1", "relation": "agent_grant", "object": f"warehouse:{warehouse}"}]}},
        timeout=5.0,
    )
    assert r.status_code in (200, 400), r.text


def test_agent_allowed_with_exact_task_grant_then_denied_after_revoke(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection, openfga_store_id: str
):
    source_sku = "SKU-900401"
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, source_sku, "WH-B", on_hand=100)
    _write_agent_grant(openfga_store_id, "WH-B")
    try:
        r = propose_with_freshness_retry(
            ontology_hot_conn, part, "WH-B",
            lambda: decision_client.post(
                "/decisions/propose",
                json={
                    "action_type": "transfer_inventory",
                    "actor": {"type": "agent", "id": "agent-1"},
                    "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
                },
            ),
        )
        body = r.json()
        assert body["authorization_result"]["outcome"] == "ALLOWED"
        assert body["status"] != "DENIED_AUTHORIZATION"
        # F32/H1: delegation chain independently recorded, not caller-asserted.
        assert body["principal_actor_id"] == "planner-1"
    finally:
        _delete_agent_grant(openfga_store_id, "WH-B")

    # Immediately after revocation: the SAME request now denies (no caching
    # of the earlier grant anywhere in the decision service's own path).
    part2 = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-900402", "WH-B", on_hand=100)
    r2 = propose_with_freshness_retry(
        ontology_hot_conn, part2, "WH-B",
        lambda: decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "agent", "id": "agent-1"},
                "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part2, "quantity": 30},
            },
        ),
    )
    body2 = r2.json()
    assert body2["status"] == "DENIED_AUTHORIZATION"
    assert inventory_unchanged(wms_client, "SKU-900402", "WH-B", 100)


def test_agent_cannot_claim_a_different_principal(
    decision_client: httpx.Client, wms_client: httpx.Client, ontology_hot_conn: psycopg.Connection
):
    """F32: 'agent impersonates human ... impossible without explicit
    delegation'. The propose request has no field for the caller to ASSERT a
    principal at all (services/decision_service/schemas.py's ActorRef is
    {type, id} only) — the delegation chain is always resolved server-side
    from OpenFGA's own agent#principal tuple, so there is nothing for a
    malicious caller to spoof."""
    part = set_inventory_and_wait(wms_client, ontology_hot_conn, "SKU-900403", "WH-B", on_hand=100)
    r = propose_with_freshness_retry(
        ontology_hot_conn, part, "WH-B",
        lambda: decision_client.post(
            "/decisions/propose",
            json={
                "action_type": "transfer_inventory",
                "actor": {"type": "agent", "id": "agent-1", "principal": "supervisor-1"},  # extra field, must be ignored
                "parameters": {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": part, "quantity": 30},
            },
        ),
    )
    body = r.json()
    # Regardless of the extra (ignored) field, the recorded delegation is
    # the REAL OpenFGA-resolved principal (planner-1), never "supervisor-1".
    assert body["principal_actor_id"] == "planner-1"
