"""Pydantic request models for the fake WMS API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class TransferRequest(BaseModel):
    action_execution_id: str
    source: str
    destination: str
    part: str
    quantity: int


class ReverseTransferRequest(BaseModel):
    action_execution_id: Optional[str] = None


class ArmFaultRequest(BaseModel):
    mode: str
    scope: str  # "next_n" | "action_execution_id"
    n: int = 1
    action_execution_id: Optional[str] = None
    params: dict[str, Any] = {}


class SetInventoryRequest(BaseModel):
    part: str
    warehouse_id: str
    on_hand: int
    reserved: int = 0
    quality_status: str = "OK"
