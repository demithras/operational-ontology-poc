"""Shared fixtures for tests/stateful/ — reuses tests/integration/conftest.py's
real-stack fixtures directly (same pattern tests/faults/conftest.py and
tests/replay/conftest.py already established)."""

from __future__ import annotations

from tests.integration.conftest import (  # noqa: F401
    decision_client,
    decision_service_reachable,
    erp_client,
    ingestion_client,
    mes_client,
    ontology_hot_conn,
    rdf4j_client,
    rdf4j_reachable,
    stack_up,
    wait_until,
    wms_client,
    wms_client_factory,
    wms_faults_reset,
)
