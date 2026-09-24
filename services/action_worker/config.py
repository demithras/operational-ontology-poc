"""Environment configuration for services/action_worker — same
one-service-owns-its-own-env pattern as services/decision_service/config.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

TASK_QUEUE = "oo-action-execution"


@dataclass(frozen=True)
class ActionWorkerConfig:
    temporal_address: str
    rdf4j_base_url: str
    rdf4j_repository: str
    wms_base_url: str
    erp_base_url: str
    mes_base_url: str
    ingestion_health_url: str


def from_env() -> ActionWorkerConfig:
    return ActionWorkerConfig(
        temporal_address=os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
        rdf4j_base_url=os.environ["RDF4J_BASE_URL"],
        rdf4j_repository=os.environ.get("RDF4J_REPOSITORY", "oo"),
        wms_base_url=os.environ["WMS_BASE_URL"],
        erp_base_url=os.environ["ERP_BASE_URL"],
        mes_base_url=os.environ["MES_BASE_URL"],
        ingestion_health_url=os.environ.get("INGESTION_HEALTH_URL", ""),
    )
