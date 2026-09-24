"""Pydantic request models for the fake ERP API."""

from __future__ import annotations

from pydantic import BaseModel


class DelayPurchaseOrderRequest(BaseModel):
    expected_at: int
    reason: str


class ExpeditePurchaseOrderRequest(BaseModel):
    action_execution_id: str
    expedite_fee: int = 0
