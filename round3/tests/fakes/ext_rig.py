"""Test rig for the P1f protocol tests: a real ExternalWorld process + honest/lying adapters + a binding for the fake variant.
(The full Byzantine catalogue H0..G3 is the H28 harness builder's job; these four are the minimum the protocol tests need.)"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from r3_shared.clock import LogicalClock
from r3_shared.extadapter import AdapterReply
from r3_shared.extobs import ObservationClient, ObserverFault
from r3_shared.extsystems import load_systems
from r3_shared.extworld import start_external
from r3_shared.identity import IdentityProvider
from r3_shared.variant import ExternalBinding
from r3_shared.world import WorldStore
from tests.fakes.fake_variant import FakeVariant


class Recorder:
    """Harness-side wrapper: logs every ExternalRequest the variant hands to the adapter."""
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


class FalseSuccess(Honest):            # L1: no write, reply OK
    adapter_id = "L1"

    def submit(self, req):
        return AdapterReply("OK", {})


class TimeoutAfterApply(Honest):       # L3: write applied, then raise (first call only)
    adapter_id = "L3"

    def __init__(self, client):
        super().__init__(client)
        self.calls = 0

    def submit(self, req):
        self.calls += 1
        r = super().submit(req)
        if self.calls == 1:
            raise TimeoutError("adapter timed out after applying")
        return r


class TargetSubstitution(Honest):      # T1: write another target with the same cap, reply OK
    adapter_id = "T1"

    def submit(self, req):
        self.client.write(req.cap, req.operation, req.target + "-evil", req.payload, self.adapter_id)
        return AdapterReply("OK", {})


class Rig:
    def __init__(self, tmp: Path, domain="manufacturing", adapter_cls=Honest, fault=None, state_dir=True, per_system=None):
        self.tmp, self.domain = Path(tmp), domain
        self.systems = load_systems(domain)
        sp = self.tmp / "systems.json"
        sp.write_text(json.dumps(self.systems))
        self.proc = start_external(self.tmp / "ext", sp, os.path.join(tempfile.mkdtemp(prefix="r3sock"), "s"))
        self.ctl = self.proc.client()
        self.clock, self.idp = LogicalClock(), IdentityProvider("secret-secret")
        self.store = WorldStore(self.tmp / "w.db")
        self.dep_id = "dep-1"
        self.recorders = {s: Recorder((per_system or {}).get(s, adapter_cls)(self.ctl.data_only())) for s in self.systems["systems"]}
        key = self.ctl.observer_key(self.dep_id)
        self.observer = ObservationClient(str(self.tmp / "ext"), key, self.systems, fault)
        self.binding = ExternalBinding(self.systems, self.recorders, {s: self.ctl.issue_root(self.dep_id, s) for s in self.systems["systems"]},
                                       self.observer, self.systems["window"])
        (self.tmp / "state").mkdir(exist_ok=True)
        self.state_dir = str(self.tmp / "state") if state_dir else None
        self.variant = FakeVariant()
        self.dep = self.deploy()
        self.tok = self.idp.issue("alice", "fake", 1000, self.clock)

    def deploy(self, external=True):
        return self.variant.deploy(self.domain, self.store.handle_factory(), self.idp.verifier(), {}, {}, self.clock,
                                   state_dir=self.state_dir, external=self.binding if external else None)

    def tick(self, n=1):
        t = self.clock.advance(n)
        self.ctl.advance(t)
        return t

    def put(self, rid, ext, key="P1"):
        return self.dep.call_tool(self.tok, "put", {"type": "Part", "key": key, "ext": ext}, request_id=rid)

    def finish(self):
        out = self.proc.close()
        return out
