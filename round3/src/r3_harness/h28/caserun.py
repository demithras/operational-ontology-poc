"""Run ONE case against ONE variant deployment (kind byz | twin) and record raw observations. No judgement here: the ledger is
only readable by the oracle after ExternalWorld close(), so classification happens in judge.py (finalize phase). The harness calls
exactly the generated schedule; the twin gets the identical step list with honest (H0) adapters (G3-E32b)."""
from __future__ import annotations

import copy
import hashlib
import os
import shutil
import tempfile

from r3_shared.anchor import AnchorClient
from r3_shared.clock import LogicalClock
from r3_shared.extadapter import canon_json
from r3_shared.extobs import ObservationClient, ObserverFault
from r3_shared.histstore import HistoryStore
from r3_shared.identity import IdentityProvider
from r3_shared.variant import ExternalBinding, g4_deploy
from r3_shared.world import WorldStore

from . import independence, specs
from .caseplay import Player
from .adapters import Composite, Recorder, Scheduler

TTL = 10 ** 6


class RunCtx:
    """Run-wide state of one variant's run: the ExternalWorld control client, the global monotone tick, cap pool for R2."""
    def __init__(self, ctl, ext_dir: str, exp_id: str, vname: str, workroot: str, anchor_sock: str | None = None, start_tick: int = 100):
        self.ctl, self.ext_dir, self.exp_id, self.vname, self.workroot = ctl, ext_dir, exp_id, vname, workroot
        self.anchor_sock, self.tick, self.cap_pool = anchor_sock, start_tick, []
        self.sock_path = getattr(ctl, "_sock", "")
        self.observer_factory = None            # tests only: a factory building a (deliberately) non-independent observer
        self.twin = None                        # G4-E26: the TWIN ExternalWorld (ctl, ext_dir); honest twins run there on the identical clock

    pending_end = None

    def settle(self) -> None:
        """Move the shared tick past the case (pair) that just ran."""
        if self.pending_end is not None:
            self.tick = max(self.tick, self.pending_end)
            self.pending_end = None

    def attach_twin(self, ctl, ext_dir: str) -> None:
        self.twin = (ctl, str(ext_dir))

    def for_kind(self, kind: str) -> "RunCtx":
        """G4-E26: a twin runs in its OWN ExternalWorld (own deployment, own clock) on the identical absolute tick schedule as its
        Byzantine case; byz/control cases use the main world. Everything else (tick counter, cap pool) is shared."""
        if kind != "twin":
            return self
        if self.twin is None:
            raise RuntimeError("G4-E26: a twin needs its own ExternalWorld (attach_twin); twins never share the byz case's world clock")
        w = copy.copy(self)
        w.ctl, w.ext_dir = self.twin
        w.sock_path = getattr(w.ctl, "_sock", "")
        return w



def _world_digest(snap: dict) -> str:
    return hashlib.sha256(canon_json({"objects": snap["objects"], "links": snap["links"]}).encode()).hexdigest()


def _default_observer(ctx, dep_id, systems, recs):
    return ObservationClient(ctx.ext_dir, ctx.ctl.observer_key(dep_id), systems, None)


def run_case(ctx: RunCtx, variant, case: dict, kind: str) -> dict:
    if kind != "twin":
        ctx.settle()                                 # a previous byz case that never got a twin (control, conformance) is over
    base, ctx = ctx, ctx.for_kind(kind)            # `base` owns the shared tick; `ctx` is the world this deployment lives in
    prims = case["prims"] if kind == "byz" else []
    dep_id = f"{ctx.exp_id}:{ctx.vname}:{case['id']}:{kind}"
    rec = {"case": case["id"], "variant": ctx.vname, "kind": kind, "dep": dep_id, "domain": case["domain"], "system": case["system"],
           "prims": prims, "crash": case.get("crash"), "idx": case["idx"], "start_tick": ctx.tick, "window": case["window"], "requests": [], "approvals": [], "dispatch": [],
           "recon": [], "unsupported": 0, "world_lock_timeout": 0, "errors": [], "deploy_error": None}
    ops, auth, systems = specs.load(case["domain"])
    if case["gen_null_ops"]:
        ops, auth = specs.with_gen_null(ops, auth)
    work = tempfile.mkdtemp(prefix="h28-", dir=ctx.workroot)
    hist = None
    try:
        clock = LogicalClock(ctx.tick)
        store = WorldStore(os.path.join(work, "world.db"), clock=clock)   # same logical clock as the other harnesses: caps/expiry see the case tick
        h = store.handle("harness-seed")
        with h.transaction(tag="seed"):
            for o in ops["seed"]["objects"]:
                h.create(o["type"], o["key"], o["props"])
            for lk in ops["seed"]["links"]:
                h.link(lk["link_type"], lk["src"], lk["dst"])
        h.close()
        h = store.handle("harness-refresh")           # deployment timing, not a world edit: evidence age is relative to the case start
        with h.transaction(tag="refresh"):
            for o in ops["seed"]["objects"]:
                if o["type"] == "EvidenceSnapshot":
                    h.update(o["type"], o["key"], {"snapshotObservedAt": clock.now()})
        h.close()
        reader = store.reader()
        idp, sched = IdentityProvider(f"h28-{dep_id}"[:64] + "-secret"), Scheduler()
        ctx.ctl.advance(clock.now())
        alt = specs.alt_targets(case["domain"], systems, ops)
        recs, comps = {}, {}
        for s in systems["systems"]:
            comps[s] = Composite(ctx.ctl.data_only(), prims, int(hashlib.sha256(f"{case['idx']}|{s}|{kind}".encode()).hexdigest()[:8], 16), sched, clock.now,
                                 alt[s], ctx.cap_pool, case["k"], case["reps"])
            recs[s] = Recorder(comps[s], s, clock.now)
        roots = {s: ctx.ctl.issue_root(dep_id, s) for s in systems["systems"]}
        observer = (ctx.observer_factory or _default_observer)(ctx, dep_id, systems, recs)
        binding = ExternalBinding(systems, recs, roots, observer, systems["window"])
        rec["topology"] = independence.check(binding, ctx.sock_path, dep_id)
        kw = {"state_dir": None, "history": None, "anchor": None}
        rec["anchor"] = bool(ctx.anchor_sock)      # G4-E23: with an anchor the auditor envelope is REQUIRED for the envelope check
        if ctx.anchor_sock:
            hist = HistoryStore(os.path.join(work, "hist.db"))
            kw.update(history=hist, anchor=AnchorClient(ctx.anchor_sock))
        else:
            kw["state_dir"] = os.path.join(work, "state")
            os.makedirs(kw["state_dir"])
        try:
            dep = g4_deploy(variant, case["domain"], store.handle_factory(), idp.verifier(), ops, auth, clock, external=binding, **kw)
        except NotImplementedError as exc:
            rec["unsupported"] += 1
            rec["errors"].append(f"deploy: {exc}")
            return rec
        except Exception as exc:  # noqa: BLE001 - a variant exception is data
            rec["deploy_error"] = f"{type(exc).__name__}: {exc}"
            return rec
        aud = getattr(type(variant), "audience", None) or "fake"
        Player(ctx, variant, case, rec, dict(ops=ops, auth=auth, systems=systems), dep, clock, idp, aud, reader, sched, observer,
                recs, comps).play()
        reader.close()
        return rec
    finally:
        if hist is not None:
            try:
                hist.close()
            except Exception:  # noqa: BLE001
                pass
        base.pending_end = max(base.pending_end or 0, rec.get("end_tick", base.tick) + 3)
        if kind == "twin" or base.twin is None:      # a byz case WITH a twin attached leaves the clock for its twin to start at the same tick
            base.settle()
        shutil.rmtree(work, ignore_errors=True)
