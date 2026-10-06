"""Test harness helpers for the Paladin variant: seed a world, deploy, issue tokens, measure effects from the world."""
from __future__ import annotations

from pathlib import Path

from paladin.core import AUDIENCE
from paladin.variant import PaladinVariant
from r3_shared.authspec import load_auth_spec
from r3_shared.clock import LogicalClock
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.world import WorldStore, diff

SECRET = "test-secret-r3-paladin"


class Rig:
    def __init__(self, tmp: Path, domain: str, mutants=(), auth_spec: dict | None = None):
        self.domain = domain
        self.ops, self.auth = load_ops_spec(domain), auth_spec or load_auth_spec(domain)
        self.clock, self.idp = LogicalClock(), IdentityProvider(SECRET)
        self.store = WorldStore(tmp / f"{domain}.sqlite")
        seed = self.store.handle("seed")
        for o in self.ops["seed"]["objects"]:
            seed.create(o["type"], o["key"], o["props"])
        for l in self.ops["seed"]["links"]:
            seed.link(l["link_type"], l["src"], l["dst"])
        self.reader = self.store.reader()
        self.dep = PaladinVariant(mutants).deploy(domain, self.store.handle_factory(), self.idp.verifier(), self.ops,
                                                  self.auth, self.clock)
        self._n = 0

    def token(self, sub: str, ttl: int = 1000, aud: str = AUDIENCE) -> str:
        return self.idp.issue(sub, aud, ttl, self.clock)

    def rid(self) -> str:
        self._n += 1
        return f"req-{self._n}"

    def snap(self) -> dict:
        return self.reader.snapshot()

    def effects_of(self, fn) -> tuple:
        """(result, world effect records) - effects measured from the world store, never from the result."""
        before = self.snap()
        res = fn()
        return res, diff(before, self.snap())
