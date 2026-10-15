"""Host-side adapter factory for H29 (G5-E8: deploy_spec adapter_factory = "r3_harness.h29.adapters_h29:build"). Wraps the FROZEN H28 catalogue
(src/r3_harness/h28/adapters.py, FREEZE_G4 hash) with the CP4/CP5 crash points (PROTOCOL-P1g P1g-3): before / after the ExternalClient write of the
effect whose correlation is the armed key. Honest (H0) adapters everywhere except the one Byzantine system of an F3-byz sequence.
HARNESS code: runs in the host process, holds only the data-plane ExternalClient (never a control path, never a root cap)."""
from __future__ import annotations

import hashlib

from r3_shared import faultplane
from r3_shared.extadapter import correlation

CP4, CP5 = "CP4_adapter_before_apply", "CP5_adapter_after_apply"


class CrashWrapped:
    """submit() with crash points; delayed writes (O2) of the catalogue are executed lazily at the next submit of ANY system."""

    def __init__(self, inner, sched, clock):
        self.inner, self.adapter_id, self.sched, self.clock = inner, inner.adapter_id, sched, clock

    def submit(self, req):
        for _, fn in self.sched.due(self.clock.now()):
            try:
                fn()
            except Exception:  # noqa: BLE001 - a delayed adversarial write failing is data in the ledger, not a harness fault
                pass
        key = correlation(req.request_id, req.effect_index)
        faultplane.crashpoint(CP4, key)
        try:
            return self.inner.submit(req)
        finally:
            faultplane.crashpoint(CP5, key)


def build(ctx: dict) -> dict:
    from r3_harness.h28 import adapters as A
    from r3_harness.h28 import specs as S
    from r3_shared.extworld import ExternalClient
    args = ctx.get("adapter_args") or {}
    byz = args.get("byz")
    domain = args["domain"]
    ops, _, systems = S.load(domain)
    alt = S.alt_targets(domain, systems, ops)
    client, sched, pool, out = ExternalClient(ctx["data_sock"]), A.Scheduler(), [], {}
    for s in ctx["systems"]["systems"]:
        prims = list(byz["prims"]) if byz and byz.get("system") == s else []
        seed = int(hashlib.sha256(f"{args.get('seed', 0)}|{s}|{ctx['deployment_id']}".encode()).hexdigest()[:8], 16)
        comp = A.Composite(client, prims, seed, sched, ctx["clock"].now, alt.get(s, []), pool, int((byz or {}).get("k", 2)), 2)
        out[s] = CrashWrapped(comp, sched, ctx["clock"])
    return out
