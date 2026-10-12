"""Gate 5 test helpers (conventional): real AuthorityService + anchor (control plane) + optional ExternalWorld, the conventional
variant deployed in-process with authority_source (resume = a fresh Service over the same stores). Hard-kill tests use
r3_shared.host.DeploymentProxy with the module-level factories below. Hand-written expectations only (frozen PROT-H29 / P1g)."""
from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from conventional.variant import AUDIENCE, ConventionalVariant
from r3_shared.anchor import start_anchor
from r3_shared.authsvc import start_authority
from r3_shared.clock import LogicalClock
from r3_shared.extadapter import AdapterReply
from r3_shared.extobs import ObservationClient
from r3_shared.extsystems import load_systems
from r3_shared.extworld import ExternalClient, start_external
from r3_shared.histstore import HistoryStore
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.variant import AuthorityBinding, ExternalBinding
from r3_shared.world import WorldStore

ROOT = Path(__file__).resolve().parents[2]
DEP = "dep-g5"
TRANSFER = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 10}
EXPEDITE = {"po_id": "PO-991", "expedite_fee": 100}
GRAPH = json.loads((ROOT / "spec" / "gate5" / "dependency-graph.json").read_text())
V0 = json.loads((ROOT / "spec" / "authority" / "manufacturing.v3.json").read_text())
LIVE: list = []


def narrowed(doc=None, drop=("transfer-inventory-planner",)):
    """A narrowing-only version: the given grants removed (never widened)."""
    d = copy.deepcopy(doc or V0)
    d["grants"] = [g for g in d["grants"] if g["id"] not in drop]
    return d


class Honest:
    adapter_id = "H0"

    def __init__(self, client):
        self.client = client

    def submit(self, req):
        r = self.client.write(req.cap, req.operation, req.target, req.payload, self.adapter_id)
        return AdapterReply("OK" if r.status == "applied" else "FAILED", {"seq": r.seq})


def honest_factory(ctx):
    """host adapter_factory form: ctx -> {system: ActionAdapter}."""
    cl = ExternalClient(ctx["data_sock"])
    return {s: Honest(cl) for s in ctx["systems"]["systems"]}


@dataclass
class G5Rig:
    tmp: Path
    clock: LogicalClock
    idp: IdentityProvider
    store: WorldStore
    reader: object
    auth: object
    actl: object
    anchor_proc: object
    anchor: object
    actl_anchor: object
    hist: HistoryStore
    variant: object
    ops: dict
    dep: object = None
    ext: object = None
    ectl: object = None
    systems: dict = None
    binding: object = None
    mutants: tuple = ()
    hosts: list = field(default_factory=list)

    def token(self, sub, ttl=100_000):
        return self.idp.issue(sub, AUDIENCE, ttl, self.clock)

    def tick(self, n=1):
        t = self.clock.advance(n)
        self.actl.advance(t)
        self.actl_anchor.advance(t)
        if self.ectl:
            self.ectl.advance(t)
        return t

    def source(self):
        from r3_shared.authsvc import AuthorityClient
        return AuthorityBinding(AuthorityClient(self.auth.sock_path, DEP), 4, GRAPH)

    def deploy(self, resume=False, mutants=None, **kw):
        v = ConventionalVariant(self.mutants if mutants is None else mutants)
        kw.setdefault("external", self.binding)
        return v.deploy("manufacturing", self.store.handle_factory(), self.idp.verifier(), self.ops, V0, self.clock, None,
                        HistoryStore(str(self.tmp / "hist.db")), self.anchor, None, authority_source=self.source(), resume=resume, **kw)

    def restart(self, mutants=None):
        """A NEW service over the surviving durable stores (what a host kill + resume gives: no in-memory object survives)."""
        self.dep = self.deploy(resume=True, mutants=mutants)
        return self.dep

    def d(self, sub, op, args, rid, obo=None):
        return self.dep.direct(self.token(sub), op, args, obo, rid)

    def commits(self):
        return [x["data"]["request_id"] for x in self.reader.log() if x["kind"] == "mark" and x["ref"] == "commit"]

    def stop(self):
        for p in (self.auth, self.anchor_proc, self.ext):
            try:
                if p is not None and p.proc.poll() is None:
                    p.proc.kill()
                    p.proc.wait()
                    for f in (p.proc.stdout, p.proc.stderr):
                        f and f.close()
            except Exception:  # noqa: BLE001
                pass
        for h in self.hosts:
            try:
                h.kill()
            except Exception:  # noqa: BLE001
                pass


def stop_all():
    while LIVE:
        LIVE.pop().stop()


def make_g5(tmp_path, mutants=(), ext=False, start=2) -> G5Rig:
    tmp = Path(tmp_path)
    tmp.mkdir(parents=True, exist_ok=True)
    short = tempfile.mkdtemp(prefix="r3g5")
    ops = load_ops_spec("manufacturing")
    clock = LogicalClock(start)
    store = WorldStore(tmp / "w.db", clock=clock)
    h = store.handle("seed")
    for o in ops["seed"]["objects"]:
        h.create(o["type"], o["key"], o["props"])
    for lk in ops["seed"]["links"]:
        h.link(lk["link_type"], lk["src"], lk["dst"])
    h.close()
    auth = start_authority(tmp / "auth", os.path.join(short, "a"))
    actl = auth.control()
    actl.publish(V0)
    actl.advance(clock.now())
    ap = start_anchor(tmp / "anchor", os.path.join(short, "s"), control=True)
    ac = ap.control()
    ac.advance(clock.now())
    rig = G5Rig(tmp, clock, IdentityProvider("test-secret-123"), store, store.reader(), auth, actl, ap, ap.client(), ac,
                HistoryStore(str(tmp / "hist.db")), None, ops, mutants=tuple(mutants))
    if ext:
        systems = load_systems("manufacturing")
        sp = tmp / "systems.json"
        sp.write_text(json.dumps(systems))
        rig.ext = start_external(tmp / "ext", sp, os.path.join(short, "e"))
        rig.ectl = rig.ext.client()
        rig.ectl.advance(clock.now())
        rig.systems = systems
        recs = {s: Honest(rig.ectl.data_only()) for s in systems["systems"]}
        obs = ObservationClient(str(tmp / "ext"), rig.ectl.observer_key(DEP), systems, None)
        rig.binding = ExternalBinding(systems, recs, {s: rig.ectl.issue_root(DEP, s) for s in systems["systems"]}, obs, systems["window"])
    rig.dep = rig.deploy()
    LIVE.append(rig)
    return rig
