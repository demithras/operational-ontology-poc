"""PaladinVariant: the r3_shared Variant for the Paladin architecture (EOO control plane on the vendored Round 2 Engine)."""
from __future__ import annotations

from paladin import mutants as _mutants
from paladin.deployment import PaladinDeployment


class PaladinVariant:
    name = "paladin"

    def __init__(self, mutants=()):
        self.mutants = _mutants.resolve(mutants)

    def with_mutants(self, *names: str) -> "PaladinVariant":
        return PaladinVariant(set(self.mutants) | set(names))

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock) -> PaladinDeployment:
        return PaladinDeployment(domain, world_handle_factory, verifier, ops_spec, auth_spec, clock, self.mutants)
