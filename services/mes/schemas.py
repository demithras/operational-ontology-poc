"""Pydantic request models for the fake MES API."""

from __future__ import annotations

from pydantic import BaseModel


class RescheduleWorkOrderRequest(BaseModel):
    new_planned_start: int
