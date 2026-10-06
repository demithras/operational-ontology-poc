"""Reference variant for protocol/world tests ONLY. Allow-all for any validly-signed token. Never registered."""
from __future__ import annotations

import hashlib
import json

from r3_shared.identity import TokenError
from r3_shared.mutants import validate
from r3_shared.variant import CallResult, ToolDescriptor


class FakeDeployment:
    def __init__(self, domain, factory, verifier, clock, auth_spec=None):
        self.auth_spec = auth_spec or {}
        self.domain, self.verifier, self.clock = domain, verifier, clock
        self.world = factory("fake-service")
        self.crashed = False

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
        if self.crashed:
            return CallResult("UNAVAILABLE", {})
        sub = self._sub(token)
        if sub is None:
            return CallResult("DENIED", {"reason": "bad token"})
        self.world.create(args["type"], args["key"], {"by": sub})
        return CallResult("OK", {})

    def read(self, token, operation, args):
        rec = self.world.get(args["type"], args["key"])
        return CallResult("OK" if rec else "UNKNOWN", rec or {})

    def approve(self, token, operation, args, requester, on_behalf_of=None):
        return CallResult("OK", {}) if self._sub(token) else CallResult("DENIED", {"reason": "bad token"})

    def set_authority(self, auth_spec):
        self.auth_spec = auth_spec

    def authority_version(self):
        return hashlib.sha256(json.dumps(self.auth_spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def crash(self):
        self.crashed = True

    def restart(self):
        self.crashed = False


class FakeVariant:
    name = "fake"

    def __init__(self, mutants=()):
        self.mutants = validate(mutants)

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock):
        return FakeDeployment(domain, world_handle_factory, verifier, clock, auth_spec)
