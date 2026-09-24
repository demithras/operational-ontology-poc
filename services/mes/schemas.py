"""Pydantic request models for the fake MES API."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class RescheduleWorkOrderRequest(BaseModel):
    new_planned_start: int
    # Optional (Phase 6, docs/experiment/briefs/phase6.md item 2) — backward
    # compatible with pre-Phase-6 callers (tests/integration/test_mes_reschedule.py)
    # that never supplied one; see services/mes/app.py for the branch.
    action_execution_id: Optional[str] = None


class SetWorkOrderRequirement(BaseModel):
    part_id: str
    qty: int


class SetWorkOrderRequest(BaseModel):
    """Phase 10 fix (docs/experiment/implementation-notes.md "self-contained
    fixtures", docs/experiment/briefs/phase10fix.md): test-mode-only exact
    upsert of one synthetic work order plus its FULL replacement BOM
    requirement set, so integration tests can build their own HIGH-priority/
    at-risk precondition instead of scavenging whichever real seeded work
    order happens to currently qualify. Same convention as
    services/wms/schemas.py::SetInventoryRequest."""

    priority: str  # LOW | MEDIUM | HIGH
    warehouse: str
    requirements: list[SetWorkOrderRequirement]
    status: str = "RELEASED"
    planned_start: int = 0
    planned_finish: int = 1
    production_line_id: str = "LINE-00"
