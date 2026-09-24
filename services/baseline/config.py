"""Environment configuration for services/baseline — same
one-service-owns-its-own-env pattern as services/decision_service/config.py
(Phase 8, docs/experiment/spec/10_ab_experiment.md Variant A)."""

from __future__ import annotations

import os
from dataclasses import dataclass

BASELINE_ACTION_TASK_QUEUE = "oo-baseline-action-execution"
BASELINE_KAFKA_CONSUMER_GROUP = "oo-baseline"


@dataclass(frozen=True)
class BaselineConfig:
    openfga_api_url: str
    opa_base_url: str
    wms_base_url: str
    erp_base_url: str
    mes_base_url: str
    baseline_ingestion_health_url: str
    temporal_address: str


def from_env() -> BaselineConfig:
    # openfga_api_url/opa_base_url/baseline_ingestion_health_url are only
    # used by services/baseline/app.py (the decision service) — optional
    # here (empty-string default) so services/baseline/worker.py (which
    # never touches OpenFGA/OPA/the ingestion health endpoint, same scoping
    # as services/action_worker/config.py) doesn't need those env vars set.
    return BaselineConfig(
        openfga_api_url=os.environ.get("OPENFGA_API_URL", ""),
        opa_base_url=os.environ.get("OPA_BASE_URL", ""),
        wms_base_url=os.environ["WMS_BASE_URL"],
        erp_base_url=os.environ["ERP_BASE_URL"],
        mes_base_url=os.environ["MES_BASE_URL"],
        baseline_ingestion_health_url=os.environ.get("BASELINE_INGESTION_HEALTH_URL", ""),
        temporal_address=os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"),
    )
