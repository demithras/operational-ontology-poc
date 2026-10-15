"""Gate 4 rig (Paladin): a real ExternalWorld process, per-system recorders around chosen adapters, a seeded world with a clock,
an observer, and the Paladin variant deployed with `external=ExternalBinding(...)`. Truth is read from the ExternalWorld ledger."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from g4_adapters import Honest, Recorder
from g2_rig import new_anchor
from paladin.core import AUDIENCE
from paladin.variant import PaladinVariant
from r3_shared.authspec import load_auth_spec
from r3_shared.clock import LogicalClock
from r3_shared.extobs import ObservationClient
from r3_shared.extsystems import load_systems
from r3_shared.extworld import start_external
from r3_shared.histstore import HistoryStore
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.variant import ExternalBinding
from r3_shared.world import WorldStore, diff

SPECS = {"manufacturing": ("manufacturing", "manufacturing"), "project": ("project.h28", "project.h28.v3")}
TR = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 60}
EXP = {"po_id": "PO-992", "expedite_fee": 100}
BIGFEE = {"po_id": "PO-992", "expedite_fee": 900}
RES = {"work_order_id": "WO-43", "new_planned_start": 55}
PUB = {"verdict": "verdict-H-D-1", "visibility": "internal"}


class G4Rig:
    def __init__(self, tmp: Path, domain="manufacturing", adapter=Honest, per_system=None, mutants=(), fault=None,
                 history=False):
        self.tmp, self.domain, self.mutants = Path(tmp), domain, tuple(mutants)
        self.tmp.mkdir(parents=True, exist_ok=True)
        ops_name, auth_name = SPECS[domain]
        self.ops, self.auth = load_ops_spec(ops_name), load_auth_spec(auth_name)
        self.systems = load_systems(domain)
        sp = self.tmp / "systems.json"
        sp.write_text(json.dumps(self.systems))
        self.ext_dir = self.tmp / "ext"
        self.proc = start_external(self.ext_dir, sp, os.path.join(tempfile.mkdtemp(prefix="r3sock"), "s"))
        self.ctl = self.proc.client()
        self.clock, self.idp = LogicalClock(), IdentityProvider("g4-secret")
        self.store = WorldStore(self.tmp / "w.sqlite", clock=self.clock)
        seed = self.store.handle("seed")
        for o in self.ops["seed"]["objects"]:
            seed.create(o["type"], o["key"], o["props"])
        for l in self.ops["seed"]["links"]:
            seed.link(l["link_type"], l["src"], l["dst"])
        self.reader = self.store.reader()
        self.dep_id = "dep-1"
        self.recorders = {s: Recorder((per_system or {}).get(s, adapter)(self.ctl.data_only())) for s in self.systems["systems"]}
        self.observer = ObservationClient(str(self.ext_dir), self.ctl.observer_key(self.dep_id), self.systems, fault)
        self.binding = ExternalBinding(self.systems, self.recorders,
                                       {s: self.ctl.issue_root(self.dep_id, s) for s in self.systems["systems"]},
                                       self.observer, self.systems["window"])
        self.anchor = new_anchor(self.tmp) if history else None
        self.history = HistoryStore(str(self.tmp / "history.sqlite")) if history else None
        self.state_dir = None if history else str(self.tmp / "state")
        self.dep = self.deploy()
        self._n = 0

    def deploy(self, external="same"):
        return PaladinVariant(self.mutants).deploy(
            self.domain, self.store.handle_factory(), self.idp.verifier(), self.ops, self.auth, self.clock,
            state_dir=self.state_dir, history=self.history, anchor=self.anchor.client() if self.anchor else None,
            external=self.binding if external == "same" else external)

    def token(self, sub: str) -> str:
        return self.idp.issue(sub, AUDIENCE, 100000, self.clock)

    def rid(self) -> str:
        self._n += 1
        return f"g4-{self._n}"

    def snap(self) -> dict:
        return self.reader.snapshot()

    def tick(self, n=1) -> int:
        t = self.clock.advance(n)
        self.ctl.advance(t)
        return t

    def call(self, sub, op, args, rid=None, obo=None):
        return self.dep.direct(self.token(sub), op, args, on_behalf_of=obo, request_id=rid or self.rid())

    def ledger(self) -> dict:
        """Truth: the ExternalWorld ledger (read-only connection)."""
        con = sqlite3.connect(f"file:{self.ext_dir / 'external.db'}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            return {t: [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY seq")] for t in ("effects", "audit")}
        finally:
            con.close()

    def settle(self, rid, extra=10):
        """dispatch, move past the cap expiry, reconcile at a watermark beyond it: the outcome list of `rid`."""
        self.dep.dispatch_pending()
        t = self.tick(extra)
        return self.dep.reconcile(rid, t + 1).body["outcomes"]

    def applied(self, correlation=None):
        rows = self.ledger()["effects"]
        return [r for r in rows if correlation is None or r["correlation"] == correlation]

    def effects_of(self, fn):
        before = self.snap()
        res = fn()
        return res, diff(before, self.snap())

    def finish(self):
        out = self.proc.close()
        if self.anchor:
            self.anchor.close()
        return out
