"""tests/faults/ shares tests/integration/'s fixtures (real docker-compose
stack — same requirement: `make up && make seed`) rather than redefining
them. Pytest picks up fixtures re-exported from another conftest.py the
same as if they were defined here directly.
"""

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
