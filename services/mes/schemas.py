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
