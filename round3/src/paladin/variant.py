"""PaladinVariant: the r3_shared Variant for the Paladin architecture (EOO control plane on the vendored Round 2 Engine)."""
from __future__ import annotations

from typing import Iterable

from paladin.deployment import PaladinDeployment
from r3_shared import mutants as _mutants


# PROT-H25 A5 (domain-branch audit): the ops-spec helper implementations of the two domains (Round 2 pack logic). Everything else
# in src/paladin decides authority / governance / disclosure generically; the static scan must find no domain, model, body,
# principal, role or relation literal outside these directories.
DOMAIN_LOGIC_MODULES = ("src/paladin/domains/manufacturing/logic", "src/paladin/domains/project/logic")


class PaladinVariant:
    name = "paladin"
    audience = "paladin"  # read by the harness as type(variant).audience
    deployment_class = PaladinDeployment

    def __init__(self, mutants: Iterable[str] = ()):
        self.mutants = _mutants.validate(mutants)

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock,
               state_dir=None, history=None, anchor=None, governance=None) -> PaladinDeployment:
        return self.deployment_class(domain, world_handle_factory, verifier, ops_spec, auth_spec, clock, self.mutants,
                                     state_dir, history, anchor, governance)
