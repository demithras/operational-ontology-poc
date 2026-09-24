"""Request/response models for the decision service HTTP API.

Security note (F31, docs/experiment/spec/09_failure_and_adversarial_matrix.md:
"tool parameter injection -> MCP/action API -> normal gates re-run
server-side"): every identifier-shaped value accepted from a caller —
action_type, actor id, and every string value inside `parameters`/`context`
— is validated here against `_ID_PATTERN` BEFORE it can reach anything that
builds a query or an authorization-object string from it (SPARQL in
services/decision_service/evidence.py, OpenFGA tuple objects in authz.py,
Postgres via psycopg's own parameterized queries in store.py). A value that
fails this check never becomes a request FastAPI will process further — it
is rejected as HTTP 422 (F01: "malformed decision -> reject; 0 external
effects") before evidence gathering, authorization, or policy evaluation
ever runs. services/common/sparql_escape.py is a SECOND, independent layer
for the one caller-supplied value that reaches a hand-built SPARQL query
(evidence.py's warehouse-existence ASK) — this validator is the primary one.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, field_validator

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def _check_id(value: str, field_name: str) -> str:
    if not _ID_PATTERN.match(value):
        raise ValueError(
            f"{field_name}={value!r} is not a valid identifier "
            f"(must match ^[A-Za-z0-9_-]{{1,64}}$)"
        )
    return value


def _validate_ids_recursively(value: Any, field_name: str) -> Any:
    """Applied to the whole `parameters`/`context` dict: every STRING value
    anywhere inside it (however nested) must be identifier-shaped. Every
    parameter this domain ever accepts that is a string is an identifier
    (warehouse/part/work-order/PO id); numeric fields (quantity, fee,
    new_planned_start) are ints and are untouched by this check."""
    if isinstance(value, str):
        _check_id(value, field_name)
    elif isinstance(value, dict):
        for k, v in value.items():
            _validate_ids_recursively(v, f"{field_name}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _validate_ids_recursively(v, f"{field_name}[{i}]")
    return value


class ActorRef(BaseModel):
    type: Literal["user", "agent"]
    id: str

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        return _check_id(v, "actor.id")


class ProposeRequest(BaseModel):
    action_type: str
    actor: ActorRef
    parameters: dict[str, Any]
    context: dict[str, Any] = {}

    @field_validator("action_type")
    @classmethod
    def _valid_action_type(cls, v: str) -> str:
        return _check_id(v, "action_type")

    @field_validator("parameters")
    @classmethod
    def _valid_parameters(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_ids_recursively(v, "parameters")

    @field_validator("context")
    @classmethod
    def _valid_context(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _validate_ids_recursively(v, "context")


class ApproveRequest(BaseModel):
    approver_id: str
    decision_content_hash: str
    scope: str = "default"

    @field_validator("approver_id")
    @classmethod
    def _valid_approver(cls, v: str) -> str:
        return _check_id(v, "approver_id")

    @field_validator("decision_content_hash")
    @classmethod
    def _valid_hash(cls, v: str) -> str:
        if not _HASH_PATTERN.match(v):
            raise ValueError("decision_content_hash must be a 64-char lowercase hex sha256")
        return v

    @field_validator("scope")
    @classmethod
    def _valid_scope(cls, v: str) -> str:
        return _check_id(v, "scope")
