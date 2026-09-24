"""Unified thin HTTP client over BOTH variants' decision-service API — same
endpoint shapes by construction (services/baseline/app.py mirrors
services/decision_service/app.py's surface), so every workload calls
`propose`/`approve`/`execute`/`get`/`replay` identically against either
`variant="ontology"` or `variant="baseline"`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from seed import db_env


@dataclass(frozen=True)
class VariantClient:
    name: str  # "ontology" | "baseline"
    base_url: str
    client: httpx.Client

    def propose(self, action_type: str, actor_type: str, actor_id: str, parameters: dict, context: dict | None = None, timeout: float = 15.0) -> httpx.Response:
        return self.client.post(
            "/decisions/propose",
            json={"action_type": action_type, "actor": {"type": actor_type, "id": actor_id}, "parameters": parameters, "context": context or {}},
            timeout=timeout,
        )

    def get(self, decision_id: str) -> httpx.Response:
        return self.client.get(f"/decisions/{decision_id}")

    def approve(self, decision_id: str, approver_id: str, decision_content_hash: str, scope: str = "default") -> httpx.Response:
        return self.client.post(f"/decisions/{decision_id}/approve", json={"approver_id": approver_id, "decision_content_hash": decision_content_hash, "scope": scope})

    def execute(self, decision_id: str) -> httpx.Response:
        return self.client.post(f"/decisions/{decision_id}/execute", timeout=15.0)

    def replay(self, decision_id: str) -> httpx.Response:
        return self.client.post(f"/replay/{decision_id}", timeout=30.0)

    def wait_terminal(self, decision_id: str, timeout_s: float = 45.0) -> dict:
        """Polls GET /decisions/{id} until it reaches an EXECUTION terminal
        status (OBSERVED_SUCCESS/DIVERGED/OUTCOME_UNKNOWN/EXECUTION_FAILED/
        ACTION_VERSION_INVALIDATED) or the timeout elapses — i.e. it
        continues polling through APPROVED/EXECUTING (both mean "not done
        yet" here, since this is only called right after execute())."""
        terminal = {"OBSERVED_SUCCESS", "DIVERGED", "OUTCOME_UNKNOWN", "EXECUTION_FAILED", "ACTION_VERSION_INVALIDATED"}
        deadline = time.monotonic() + timeout_s
        last = self.get(decision_id).json()
        while time.monotonic() < deadline and last.get("status") not in terminal:
            time.sleep(1.0)
            last = self.get(decision_id).json()
        return last


def make_clients() -> dict[str, VariantClient]:
    db_env.load_dotenv()
    return {
        "ontology": VariantClient("ontology", db_env.decision_service_url(), httpx.Client(base_url=db_env.decision_service_url(), timeout=15.0)),
        "baseline": VariantClient("baseline", db_env.baseline_service_url(), httpx.Client(base_url=db_env.baseline_service_url(), timeout=15.0)),
    }
