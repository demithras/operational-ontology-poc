"""Gate 5 test adapter factory for spawned hosts (deploy_spec external.adapter_factory = "g5_adapters:build")."""
from __future__ import annotations

from g4_adapters import Honest
from r3_shared.extworld import ExternalClient


def build(ctx: dict) -> dict:
    client = ExternalClient(ctx["data_sock"], None)
    return {s: Honest(client) for s in ctx["systems"]["systems"]}
