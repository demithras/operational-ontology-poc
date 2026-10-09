"""Gate 4 test helpers (conventional): a real ExternalWorld process, harness-style adapters, the conventional variant deployed
with `external=`. Hand-written expectations only (frozen PROT-H28 / PROTOCOL-P1f); nothing here imports the oracle or harness."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from conventional.variant import AUDIENCE, ConventionalVariant
from r3_shared.authspec import load_auth_spec
from r3_shared.clock import LogicalClock
from r3_shared.extadapter import AdapterReply
from r3_shared.extobs import ObservationClient
from r3_shared.extsystems import load_systems
from r3_shared.extworld import start_external
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.variant import ExternalBinding
from r3_shared.world import WorldStore, diff

ROOT = Path(__file__).resolve().parents[2]
EXPEDITE = {"po_id": "PO-991", "expedite_fee": 100}
BIG_EXPEDITE = {"po_id": "PO-991", "expedite_fee": 900}
TRANSFER = {"source_warehouse": "WH-B", "destination_warehouse": "WH-A", "part": "PX-17", "quantity": 10}
RESCHEDULE = {"work_order_id": "WO-43", "new_planned_start": 35}


class Recorder:
    def __init__(self, inner):
        self.inner, self.adapter_id, self.log = inner, inner.adapter_id, []

    def submit(self, req):
        self.log.append(req)
        return self.inner.submit(req)


class Honest:
    adapter_id = "H0"

    def __init__(self, client):
        self.client = client

    def submit(self, req):
        r = self.client.write(req.cap, req.operation, req.target, req.payload, self.adapter_id)
        return AdapterReply("OK" if r.status == "applied" else "FAILED", {"seq": r.seq})


class FalseSuccess(Honest):
    adapter_id = "L1"

    def submit(self, req):
        return AdapterReply("OK", {})


class FalseFailure(Honest):
    adapter_id = "L2"

    def submit(self, req):
        super().submit(req)
        return AdapterReply("FAILED", {})


class TimeoutAfterApply(Honest):
    adapter_id = "L3"

    def submit(self, req):
        super().submit(req)
        raise TimeoutError("lost the reply")


class Omit(Honest):
    adapter_id = "O1"

    def submit(self, req):
        return AdapterReply("TIMEOUT", {})


class TargetSubst(Honest):
    adapter_id = "T1"

    def submit(self, req):
        self.client.write(req.cap, req.operation, req.target + "-evil", req.payload, self.adapter_id)
        return AdapterReply("OK", {})


class PayloadMut(Honest):
    adapter_id = "T2"

    def submit(self, req):
        self.client.write(req.cap, req.operation, req.target, {**req.payload, "x": 10}, self.adapter_id)
        return AdapterReply("OK", {})


class Dup(Honest):
    adapter_id = "R1"

    def submit(self, req):
        for _ in range(3):
            super().submit(req)
        return AdapterReply("OK", {})


class PolicyReply(Honest):
    adapter_id = "G1"

    def submit(self, req):
        return AdapterReply("FAILED", {"reason": "policy: fee exceeds limit", "decision": "deny", "approval": {"by": "admin-1"},
                                       "grant": "everything", "on_behalf_of": "admin-1", "status": "approved"})


@dataclass
class G4Rig:
    domain: str
    tmp: Path
    proc: object
    ctl: object
    systems: dict
    store: WorldStore
    reader: object
    clock: LogicalClock
    idp: IdentityProvider
    recorders: dict
    observer: ObservationClient
    binding: ExternalBinding
    dep: object
    variant: object
    ops: dict
    auth: dict

    def token(self, sub, ttl=100_000):
        return self.idp.issue(sub, AUDIENCE, ttl, self.clock)

    def snap(self):
        return self.reader.snapshot()

    def tick(self, n=1):
        t = self.clock.advance(n)
        self.ctl.advance(t)
        return t

    def ledger(self, table="effects"):
        con = sqlite3.connect(f"file:{self.tmp / 'ext' / 'external.db'}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in con.execute(f"SELECT * FROM {table} ORDER BY seq")]
        finally:
            con.close()

    def sent(self, system):
        return self.recorders[system].log

    def stop(self):
        try:
            self.proc.close()
        except Exception:  # noqa: BLE001
            pass


_LIVE: list = []


def stop_all():
    while _LIVE:
        _LIVE.pop().stop()


def make_g4(tmp_path, domain="manufacturing", mutants=(), adapters=None, default=Honest, fault=None, start=2):
    tmp = Path(tmp_path)
    tmp.mkdir(parents=True, exist_ok=True)
    systems = load_systems(domain)
    sp = tmp / "systems.json"
    sp.write_text(json.dumps(systems))
    proc = start_external(tmp / "ext", sp, os.path.join(tempfile.mkdtemp(prefix="r3sock"), "s"))
    ctl = proc.client()
    ops_name = "project.h28" if domain == "project" else domain
    ops = json.loads((ROOT / "spec" / "ops" / f"{ops_name}.json").read_text())
    auth = json.loads((ROOT / "spec" / "authority" / "project.h28.v3.json").read_text()) if domain == "project" \
        else load_auth_spec(domain)
    store = WorldStore(tmp / "w.db")
    h = store.handle("seed")
    for o in ops["seed"]["objects"]:
        h.create(o["type"], o["key"], o["props"])
    for l in ops["seed"]["links"]:
        h.link(l["link_type"], l["src"], l["dst"])
    h.close()
    clock, idp = LogicalClock(start), IdentityProvider("test-secret-123")
    ctl.advance(clock.now())
    recs = {s: Recorder((adapters or {}).get(s, default)(ctl.data_only())) for s in systems["systems"]}
    observer = ObservationClient(str(tmp / "ext"), ctl.observer_key("dep-1"), systems, fault)
    binding = ExternalBinding(systems, recs, {s: ctl.issue_root("dep-1", s) for s in systems["systems"]}, observer,
                              systems["window"])
    variant = ConventionalVariant(mutants)
    dep = variant.deploy(domain, store.handle_factory(), idp.verifier(), ops, auth, clock, external=binding)
    rig = G4Rig(domain, tmp, proc, ctl, systems, store, store.reader(), clock, idp, recs, observer, binding, dep, variant, ops, auth)
    _LIVE.append(rig)
    return rig


PUBLISH_PUBLIC = {"verdict": "verdict-H-D-1", "visibility": "public"}
PUBLISH_PRIVATE = {"verdict": "verdict-H-D-1", "visibility": "internal"}
NOTIFY = {"hypothesis": "H-A", "reviewer": "researcher-2"}
