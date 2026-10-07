"""Reference variant for protocol/world tests ONLY. Allow-all for any validly-signed token. Never registered."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from r3_shared.identity import TokenError
from r3_shared.mutants import validate
from r3_shared.variant import CallResult, ToolDescriptor
from tests.fakes.fake_g2 import G2Mixin


class FakeDeployment(G2Mixin):
    """Correct fake (PROT-H23-A8): request_id ledger is durable in state_dir, written before the world commit
    and after the before_commit crash point; a lock serialises authorize->commit."""
    durable_ledger = True

    def __init__(self, domain, factory, verifier, clock, auth_spec=None, state_dir=None, history=None, anchor=None):
        self.auth_spec = auth_spec or {}
        self.domain, self.verifier, self.clock = domain, verifier, clock
        self.factory, self.state_dir = factory, state_dir
        self.world = factory("fake-service")
        self.crashed, self._armed, self._lock = False, None, threading.Lock()
        self._mem_ledger = set()
        self._g2_init(history, anchor)

    # --- ledger -------------------------------------------------------------
    def _ledger_path(self):
        return Path(self.state_dir) / "ledger.json" if self.state_dir else None

    def _ledger(self):
        p = self._ledger_path()
        if self.durable_ledger and p is not None:
            return set(json.loads(p.read_text())) if p.exists() else set()
        return self._mem_ledger

    def _record(self, rid):
        led = self._ledger() | {rid}
        p = self._ledger_path()
        if self.durable_ledger and p is not None:
            p.write_text(json.dumps(sorted(led)))
        else:
            self._mem_ledger = led

    def _sub(self, token):
        try:
            return self.verifier.verify(token, "fake", self.clock)
        except TokenError:
            return None

    def tools(self, token):
        return [ToolDescriptor("put", {"type": "object"})] if self._sub(token) else []

    def call_tool(self, token, name, args, on_behalf_of=None, request_id=None):
        return self.direct(token, name, args, on_behalf_of, request_id) if name == "put" else CallResult("UNKNOWN", {})

    def direct(self, token, operation, args, on_behalf_of=None, request_id=None):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            sub = self._sub(token)
            if sub is None:
                return CallResult("DENIED", {"reason": "bad token"})
            if request_id is not None and request_id in self._ledger():
                return CallResult("OK", {"replayed": True})
            return self._commit(sub, args, request_id, on_behalf_of)

    def _commit(self, sub, args, request_id, obo=None):
        armed, self._armed = self._armed, None
        if armed == "before_commit":
            self.crashed = True
            return CallResult("UNKNOWN", {"reason": "crashed"})
        if request_id is not None:
            self._record(request_id)
        with self.world.transaction(tag="effect") as tx:
            rec = self.world.get(args["type"], args["key"])
            if rec is None:
                self.world.create(args["type"], args["key"], {"by": sub, "n": 1})
            else:
                self.world.update(args["type"], args["key"], {"by": sub, "n": rec["props"].get("n", 1) + 1})
            seq = tx.mark("commit", {"request_id": request_id, "kind": "direct", "authority_version": self.authority_version()})
        if request_id is not None:
            self.g2["used"][request_id] = {"authority_version": self.authority_version(), "world_seq": seq,
                                           "tick": tx.tick, "path": [], "on_behalf_of": obo}
            self._g2_save()
        if armed == "after_commit":
            self.crashed = True
            return CallResult("UNKNOWN", {"reason": "crashed"})
        return self._g2_anchor(request_id, "direct", sub, seq, tx.tick, {}) if request_id is not None else CallResult("OK", {})

    def read(self, token, operation, args):
        rec = self.world.get(args["type"], args["key"])
        return CallResult("OK" if rec else "UNKNOWN", rec or {"reason": "absent"})

    def approve(self, token, operation, args, requester, on_behalf_of=None):
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            if not self._sub(token):
                return CallResult("DENIED", {"reason": "bad token"})
            armed, self._armed = self._armed, None
            if armed:
                self.crashed = True
                return CallResult("UNKNOWN", {"reason": "crashed"})
            return CallResult("OK", {})

    def set_authority(self, auth_spec):
        self.auth_spec = auth_spec

    def authority_version(self):
        return hashlib.sha256(json.dumps(self.auth_spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def arm_crash(self, point):
        if point not in ("before_commit", "after_commit"):
            raise ValueError(point)
        self._armed = point

    def crash(self):
        self.crashed = True
        self._mem_ledger = set()

    def restart(self):
        self.crashed, self._armed, self._mem_ledger = False, None, set()
        self.world = self.factory("fake-service")
        self._g2_init(self.history, self.anchor)


class FakeVolatileLedger(FakeDeployment):
    """Deliberately broken: the committed-request record lives only in memory, so crash + replay double-commits."""
    durable_ledger = False


class FakeVariant:
    name = "fake"

    def __init__(self, mutants=()):
        self.mutants = validate(mutants)

    deployment_class = FakeDeployment

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock, state_dir=None,
               history=None, anchor=None):
        return self.deployment_class(domain, world_handle_factory, verifier, clock, auth_spec, state_dir, history, anchor)


class FakeVolatileVariant(FakeVariant):
    name = "fake-volatile"
    deployment_class = FakeVolatileLedger
