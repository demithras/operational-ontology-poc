"""PaladinVariant: the r3_shared Variant for the Paladin architecture (EOO control plane on the vendored Round 2 Engine)."""
from __future__ import annotations

from typing import Iterable

from paladin.deployment import PaladinDeployment
from r3_shared import mutants as _mutants


class PaladinVariant:
    name = "paladin"
    audience = "paladin"  # read by the harness as type(variant).audience
    deployment_class = PaladinDeployment

    def __init__(self, mutants: Iterable[str] = ()):
        self.mutants = _mutants.validate(mutants)

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock) -> PaladinDeployment:
        return self.deployment_class(domain, world_handle_factory, verifier, ops_spec, auth_spec, clock, self.mutants)
