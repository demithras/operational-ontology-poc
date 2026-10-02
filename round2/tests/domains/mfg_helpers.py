"""Shared helpers for the manufacturing end-to-end tests."""
from __future__ import annotations

import copy

from domains._pack import boot, load_ir
from domains.manufacturing.pack import build_pack, load_seed

T0 = "2026-01-01T00:00:00+00:00"  # = EvidenceSnapshot ES-1 observation time in the seed
NOW = "2026-01-01T00:00:02+00:00"  # 2 s after the snapshot: FRESH (limit 5 s)
LATER = "2026-01-01T00:01:00+00:00"  # 60 s: STALE


def make(seed=None, clock=NOW, package=None, **kw):
    pack = build_pack(seed)
    e = boot("manufacturing", pack, clock=lambda: clock, package=package, **kw)
    return e, pack[1][("external_call", "WMS")], pack


def seed_with(mutator) -> dict:
    s = copy.deepcopy(load_seed())
    mutator(s)
    return s


def transfer_inputs(**over):
    base = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
    base.update(over)
    return base


def propose_transfer(e, who="planner-1", key="k1", **over):
    return e.propose("transfer_inventory", transfer_inputs(**over), who, idempotency_key=key)


class Snap:
    """Everything an Engine run could have changed; equality = zero effects."""

    def __init__(self, e, wms):
        self.e, self.wms = e, wms
        self.state, self.effects, self.calls = e.state().state_hash(), len(e.effect_log.entries()), len(wms.calls)

    def unchanged(self) -> bool:
        return (self.e.state().state_hash(), len(self.e.effect_log.entries()), len(self.wms.calls)) == \
            (self.state, self.effects, self.calls)


def gate(rec, name):
    return next((g for g in rec["gates"] if g["gate"] == name), None)


def failed_gates(rec):
    return [g["gate"] for g in rec["gates"] if not g["passed"]]
