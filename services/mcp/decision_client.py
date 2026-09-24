"""Thin HTTP client wrapping services/decision_service's real API — the
ONLY way any MCP tool ever reaches governance (spec 06: "Recommended tools
... as thin clients of the decision service"). No gate logic is
duplicated here: authorization, policy, SHACL conformance, approval-hash
verification, and execute()'s immutable-tuple check all happen exactly
once, server-side, inside decision_service — see propose_flow.py/app.py.
This module cannot bypass any of that even if it wanted to; it can only
call the same HTTP endpoints a human/API caller would.

F31 (tool parameter injection): this client applies NO extra trust to its
caller's values — every field is passed straight through to
decision_service, whose own services/decision_service/schemas.py rejects
anything not identifier-shaped (HTTP 422, zero effects) before evidence
gathering ever starts. Duplicating that validation here would only create
a second copy that could drift; the real gate is the one server-side copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class DecisionServiceError(Exception):
    status_code: int
    detail: Any

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"decision_service HTTP {self.status_code}: {self.detail}"


class DecisionServiceClient:
    """Synchronous — matches this whole repo's established sync-everywhere
    style (services/action_worker/activities.py's own docstring calls this
    out explicitly) and keeps FastMCP's tool functions plain `def`s."""

    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        resp = self._client.request(method, path, **kwargs)
        try:
            body = resp.json()
        except ValueError:
            body = {"detail": resp.text}
        if resp.status_code >= 400 and resp.status_code != 503:
            # 503 (GATE_UNAVAILABLE / F22-F26 dependency outage) still
            # carries a real, meaningful body the caller needs to see (a
            # governed Decision may already exist) — only genuine client
            # errors (4xx other than the honest-unavailable case) raise.
            raise DecisionServiceError(resp.status_code, body)
        return body

    def propose_transfer_inventory(
        self,
        agent_id: str,
        source_warehouse: str,
        destination_warehouse: str,
        part: str,
        quantity: int,
        work_order: str | None = None,
    ) -> dict:
        parameters: dict[str, Any] = {
            "source_warehouse": source_warehouse,
            "destination_warehouse": destination_warehouse,
            "part": part,
            "quantity": quantity,
        }
        if work_order is not None:
            parameters["work_order"] = work_order
        return self._request(
            "POST",
            "/decisions/propose",
            json={
                # actor is ALWAYS this server's own configured agent
                # identity — never taken from a tool-call argument (F32).
                "actor": {"type": "agent", "id": agent_id},
                "action_type": "transfer_inventory",
                "parameters": parameters,
            },
        )

    def get_decision(self, decision_id: str) -> dict:
        return self._request("GET", f"/decisions/{decision_id}")

    def execute_approved_decision(self, decision_id: str) -> dict:
        return self._request("POST", f"/decisions/{decision_id}/execute")

    def get_execution(self, execution_id: str) -> dict | None:
        try:
            return self._request("GET", f"/executions/{execution_id}")
        except DecisionServiceError as exc:
            if exc.status_code == 404:
                return None
            raise

    def get_outcome(self, outcome_id: str) -> dict | None:
        try:
            return self._request("GET", f"/outcomes/{outcome_id}")
        except DecisionServiceError as exc:
            if exc.status_code == 404:
                return None
            raise
