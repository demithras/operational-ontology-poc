"""Pydantic request models for the fake ERP API."""

from __future__ import annotations

from pydantic import BaseModel


class DelayPurchaseOrderRequest(BaseModel):
    expected_at: int
    reason: str
