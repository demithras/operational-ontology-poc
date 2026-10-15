"""Gate 5 test adapter factory for spawned hosts (deploy_spec external.adapter_factory = "g5_adapters:build")."""
from __future__ import annotations

from g4_adapters import Honest
from r3_shared.extworld import ExternalClient


def build(ctx: dict) -> dict:
    client = ExternalClient(ctx["data_sock"], None)
    return {s: Honest(client) for s in ctx["systems"]["systems"]}


class CrashWrap:
    """Stands in for the harness adapter wrapper of P1g-3 (CP4 before / CP5 after the ExternalClient write of correlation == key)."""

    def __init__(self, inner):
        self.inner, self.adapter_id = inner, inner.adapter_id

    def submit(self, req):
        from r3_shared import faultplane
        from r3_shared.extadapter import correlation
        key = correlation(req.request_id, req.effect_index)
        faultplane.crashpoint("CP4_adapter_before_apply", key)
        reply = self.inner.submit(req)
        faultplane.crashpoint("CP5_adapter_after_apply", key)
        return reply


def build_cp(ctx: dict) -> dict:
    return {s: CrashWrap(a) for s, a in build(ctx).items()}
