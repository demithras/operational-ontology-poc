"""Read-only hot-projection access for the MCP tools that only INSPECT
context (get_object, query_work_order_risk, list_transfer_candidates) —
never propose/execute anything. Reuses
services/projection_builder/reader.py's existing point-read functions
directly, the same "Decision API / MCP sits above the hot-projection box"
relationship docs/experiment/spec/04_architecture.md's component diagram
already describes (that module's own docstring says exactly this: "A
future Decision API (Phase 5) is the eventual production caller").

Every function here takes ONLY typed, ID-pattern-shaped arguments (never a
raw SQL/SPARQL string) — this is what keeps `get_object` from becoming the
generic `run_sql` tool spec 06 explicitly forbids exposing to an agent.
Connections are opened per call and closed immediately (autocommit,
read-only) — no pooling needed for a local single-agent POC server.
"""

from __future__ import annotations

import re

import psycopg

from services.projection_builder import reader

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

OBJECT_KINDS = ("work_order", "inventory_lot")


class InvalidObjectRequest(ValueError):
    pass


def _validate_id(value: str, field: str) -> str:
    if not _ID_PATTERN.match(value):
        raise InvalidObjectRequest(f"{field}={value!r} is not a valid identifier")
    return value


def _connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, connect_timeout=5, autocommit=True)


def query_work_order_risk(dsn: str, work_order_id: str) -> dict | None:
    _validate_id(work_order_id, "work_order_id")
    with _connect(dsn) as conn:
        return reader.get_work_order_risk(conn, work_order_id)


def list_transfer_candidates(dsn: str, work_order_id: str) -> list[dict]:
    _validate_id(work_order_id, "work_order_id")
    with _connect(dsn) as conn:
        return reader.get_transfer_candidates(conn, work_order_id)


def get_object(dsn: str, kind: str, object_id: str, warehouse: str | None = None) -> dict | None:
    """Bounded, typed object lookup — the two kinds this domain's hot
    projections cover. Anything outside {work_order, inventory_lot} is
    rejected explicitly rather than falling through to an open-ended query.
    """
    if kind not in OBJECT_KINDS:
        raise InvalidObjectRequest(f"kind={kind!r} must be one of {OBJECT_KINDS}")
    _validate_id(object_id, "object_id")
    with _connect(dsn) as conn:
        if kind == "work_order":
            return reader.get_work_order_risk(conn, object_id)
        # kind == "inventory_lot": keyed by (part, warehouse), matching
        # current_inventory's own primary key — warehouse is required here.
        if not warehouse:
            raise InvalidObjectRequest("kind='inventory_lot' requires a warehouse")
        _validate_id(warehouse, "warehouse")
        return reader.get_current_inventory(conn, object_id, warehouse)
