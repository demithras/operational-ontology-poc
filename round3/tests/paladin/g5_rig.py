"""Gate 5 rig (Paladin): REAL AuthorityService + anchor + ExternalWorld processes, a seeded world, and the Paladin variant deployed either
in-process (fast, inspectable) or in a spawned host (hard kill / resume). Truth is read from the services' own logs and the world store."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from g4_adapters import Honest
from paladin.core import AUDIENCE
from paladin.variant import PaladinVariant
from r3_shared.anchor import start_anchor
from r3_shared.authsvc import start_authority
from r3_shared.authspec import load_auth_spec
from r3_shared.clock import LogicalClock
from r3_shared.extobs import ObservationClient
from r3_shared.extsystems import load_systems
from r3_shared.extworld import start_external
from r3_shared.histstore import HistoryStore
from r3_shared.host import DeploymentProxy
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.variant import AuthorityBinding, ExternalBinding
from r3_shared.world import WorldReader, WorldStore

ROUND3 = Path(__file__).resolve().parents[2]
GRAPH_PATH = ROUND3 / "spec" / "gate5" / "dependency-graph.json"
SECRET = "g5-paladin-secret"
DEP = "dep-g5"
TR = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
EXP = {"po_id": "PO-992", "expedite_fee": 100}
RES = {"work_order_id": "WO-43", "new_planned_start": 55}
AUTH_NAME = "manufacturing.v3"


def narrowed(doc: dict, op: str = "transfer_inventory") -> dict:
    """The doc minus every grant of `op` (narrowing only): a stale-sensitive version for F6."""
    d = json.loads(json.dumps(doc))
    d["grants"] = [g for g in d["grants"] if g.get("operation") != op]
    return d


class G5Rig:
    def __init__(self, tmp=None, domain="manufacturing", external=True, mutants=(), history=True, inproc=True, auth_name=AUTH_NAME):
        self.root = Path(tempfile.mkdtemp(prefix="r3g5"))
        self.domain, self.mutants, self.history_on = domain, tuple(mutants), history
        self.ops, self.auth0 = load_ops_spec(domain), load_auth_spec(auth_name)
        self.clock, self.idp = LogicalClock(), IdentityProvider(SECRET)
        self.world_path = self.root / "world.db"
        self.store = WorldStore(self.world_path, clock=self.clock)
        seed = self.store.handle("seed")
        for o in self.ops["seed"]["objects"]:
            seed.create(o["type"], o["key"], o["props"])
        for lk in self.ops["seed"]["links"]:
            seed.link(lk["link_type"], lk["src"], lk["dst"])
        self.auth = start_authority(self.root / "auth", self.root / "a.sock")
        self.actl = self.auth.control()
        self.actl.publish(self.auth0)
        self.anchor = start_anchor(self.root / "anchor", self.root / "n.sock", control=True)
        self.nctl = self.anchor.control()
        self.systems = load_systems(domain)
        self.proc = self.ctl = None
        if external:
            sp = self.root / "systems.json"
            sp.write_text(json.dumps(self.systems))
            self.proc = start_external(self.root / "ext", sp, self.root / "e.sock")
            self.ctl = self.proc.client()
        self.hosts: list = []
        self.reader = WorldReader(str(self.world_path))
        self.dep = self.deploy() if inproc else None
        self._n = 0

    # ---- deployments --------------------------------------------------------------------------------------------------------
    def binding(self):
        return AuthorityBinding(self.auth.client(DEP), 4, json.loads(GRAPH_PATH.read_text()))

    def external_binding(self):
        if self.ctl is None:
            return None
        ad = {s: Honest(self.ctl.data_only()) for s in self.systems["systems"]}
        obs = ObservationClient(str(self.root / "ext"), self.ctl.observer_key(DEP), self.systems, None)
        return ExternalBinding(self.systems, ad, {s: self.ctl.issue_root(DEP, s) for s in self.systems["systems"]}, obs, self.systems["window"])

    def deploy(self, resume=False, mutants=None, with_auth=True):
        hist = HistoryStore(str(self.root / "hist.db")) if self.history_on else None
        return PaladinVariant(self.mutants if mutants is None else mutants).deploy(
            self.domain, self.store.handle_factory(), self.idp.verifier(), self.ops, self.auth0, self.clock,
            state_dir=None if hist else str(self.root / "state"), history=hist,
            anchor=self.anchor.client() if hist else None, external=self.external_binding(),
            authority_source=self.binding() if with_auth else None, resume=resume)

    def spec(self, resume=False, tick=0, with_ext=True):
        s = {"domain": self.domain, "ops_spec_path": str(ROUND3 / "spec" / "ops" / f"{self.domain}.json"), "auth_spec": self.auth0,
             "world_path": str(self.world_path), "secret": SECRET, "clock_start": tick,
             "state_dir": None if self.history_on else str(self.root / "state"),
             "history_path": str(self.root / "hist.db") if self.history_on else None,
             "anchor_sock": self.anchor.sock_path if self.history_on else None, "governance": None, "resume": resume,
             "deployment_id": DEP, "authority": {"sock": self.auth.sock_path, "lease": 4, "graph_path": str(GRAPH_PATH)}, "external": None}
        if self.ctl is not None and with_ext:
            s["external"] = {"systems": self.systems, "data_sock": self.proc.sock_path, "root_caps": {x: self.ctl.issue_root(DEP, x) for x in self.systems["systems"]},
                             "observer": {"ext_dir": str(self.root / "ext"), "key": self.ctl.observer_key(DEP), "fault": None},
                             "window": self.systems["window"], "adapter_factory": "g5_adapters:build", "adapter_args": {}}
        return s

    def host(self, resume=False, tick=0, mutants=None):
        w = self.root / "work"
        w.mkdir(exist_ok=True)
        px = DeploymentProxy.start("paladin", self.mutants if mutants is None else mutants, self.spec(resume, tick), str(w),
                                   extra_paths=[str(ROUND3), str(Path(__file__).parent)])
        self.hosts.append(px)
        return px

    # ---- harness helpers --------------------------------------------------------------------------------------------------
    def token(self, sub: str, ttl: int = 100000) -> str:
        return self.idp.issue(sub, AUDIENCE, ttl, self.clock)

    def rid(self) -> str:
        self._n += 1
        return f"g5-{self._n}"

    def tick(self, n=1, px=None) -> int:
        t = self.clock.advance(n)
        self.sync(t)
        if px is not None:
            px.advance(t)
        return t

    def sync(self, t: int) -> None:
        self.actl.advance(t)
        self.nctl.advance(t)
        if self.ctl is not None:
            self.ctl.advance(t)

    def call(self, sub, op, args, rid=None, dep=None):
        return (dep or self.dep).direct(self.token(sub), op, args, request_id=rid or self.rid())

    def commits(self) -> list:
        r = WorldReader(str(self.world_path))
        try:
            return [x["data"]["request_id"] for x in r.log() if x["kind"] == "mark" and x["ref"] == "commit"]
        finally:
            r.close()

    def finish(self):
        for h in self.hosts:
            try:
                h.close() if h.alive else None
            except Exception:  # noqa: BLE001
                pass
            if h.proc.poll() is None:
                h.kill()
        for closer in (lambda: self.auth.close(), lambda: self.anchor.close(), lambda: self.proc.close() if self.proc else None):
            try:
                closer()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(self.root, ignore_errors=True)
