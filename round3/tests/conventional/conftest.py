"""Fixtures: a fresh world per test, seeded from the ops spec seed; tokens from the shared identity provider."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from conventional.variant import AUDIENCE, ConventionalVariant
from r3_shared.authspec import load_auth_spec
from r3_shared.clock import LogicalClock
from r3_shared.identity import IdentityProvider
from r3_shared.opsspec import load_ops_spec
from r3_shared.world import WorldStore


@dataclass
class Rig:
    domain: str
    store: WorldStore
    reader: object
    clock: LogicalClock
    idp: IdentityProvider
    dep: object
    ops: dict
    auth: dict

    def token(self, sub: str, ttl: int = 1000, aud: str = AUDIENCE) -> str:
        return self.idp.issue(sub, aud, ttl, self.clock)

    def snap(self) -> dict:
        return self.reader.snapshot()


def make_rig(tmp_path, domain: str, mutants=(), start: int = 2) -> Rig:
    ops, auth = load_ops_spec(domain), load_auth_spec(domain)
    store = WorldStore(tmp_path / f"{domain}.db")
    h = store.handle("seed")
    for o in ops["seed"]["objects"]:
        h.create(o["type"], o["key"], o["props"])
    for l in ops["seed"]["links"]:
        h.link(l["link_type"], l["src"], l["dst"])
    h.close()
    clock, idp = LogicalClock(start), IdentityProvider("test-secret-123")
    dep = ConventionalVariant(mutants).deploy(domain, store.handle_factory(), idp.verifier(), ops, auth, clock)
    return Rig(domain, store, store.reader(), clock, idp, dep, ops, auth)


@pytest.fixture
def mfg(tmp_path):
    return make_rig(tmp_path, "manufacturing")


@pytest.fixture
def proj(tmp_path):
    return make_rig(tmp_path, "project")


@pytest.fixture
def make(tmp_path):
    n = iter(range(10_000))

    def _make(domain, mutants=(), start=2):
        d = tmp_path / f"rig{next(n)}"
        d.mkdir()
        return make_rig(d, domain, mutants, start)
    return _make


@pytest.fixture(autouse=True)
def _stop_g3_anchors():
    """make_g3(history=True) starts a real anchor_server process per rig and nothing stops it: kill them after each test
    (otherwise the session-level ANCHOR LEAK check fails, serial or sharded)."""
    yield
    import sys
    mod = sys.modules.get("conv_g3_util")
    if mod is not None:
        mod.stop_live_anchors()
