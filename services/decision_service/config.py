"""Environment configuration for the decision service.

Same one-service-owns-its-own-env pattern as services/common/db.py's
dsn_from_env: read required env vars, raise loudly (KeyError) if missing,
never silently default to a guessed URL (common.md honesty rule). Inside
docker-compose these are always set (docker-compose.yml's `decision_service`
service). For host-side scripts/tests, build a DecisionServiceConfig from
seed/db_env.py's helpers instead of relying on this module's env lookup —
see services/decision_service/bootstrap_openfga.py for the pattern.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionServiceConfig:
    rdf4j_base_url: str
    rdf4j_repository: str
    openfga_api_url: str
    opa_base_url: str
    wms_base_url: str
    erp_base_url: str
    mes_base_url: str
    ingestion_health_url: str


def from_env() -> DecisionServiceConfig:
    return DecisionServiceConfig(
        rdf4j_base_url=os.environ["RDF4J_BASE_URL"],
        rdf4j_repository=os.environ.get("RDF4J_REPOSITORY", "oo"),
        openfga_api_url=os.environ["OPENFGA_API_URL"],
        opa_base_url=os.environ["OPA_BASE_URL"],
        wms_base_url=os.environ["WMS_BASE_URL"],
        erp_base_url=os.environ["ERP_BASE_URL"],
        mes_base_url=os.environ["MES_BASE_URL"],
        # Phase 5 fix (watermark-based evidence freshness): decision_service
        # reads services/ingestion's per-source watermark from its health
        # endpoint rather than re-deriving pipeline lag itself.
        ingestion_health_url=os.environ["INGESTION_HEALTH_URL"],
    )
