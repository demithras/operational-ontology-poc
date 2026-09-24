"""Environment configuration for services/reconciliation."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ReconciliationConfig:
    rdf4j_base_url: str
    rdf4j_repository: str
    poll_interval_s: float


def from_env() -> ReconciliationConfig:
    return ReconciliationConfig(
        rdf4j_base_url=os.environ["RDF4J_BASE_URL"],
        rdf4j_repository=os.environ.get("RDF4J_REPOSITORY", "oo"),
        poll_interval_s=float(os.environ.get("OO_RECONCILIATION_POLL_INTERVAL_S", "2")),
    )
