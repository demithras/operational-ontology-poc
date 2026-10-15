"""PaladinVariant: the r3_shared Variant for the Paladin architecture (EOO control plane on the vendored Round 2 Engine)."""
from __future__ import annotations

from typing import Iterable

from paladin.deployment import PaladinDeployment
from r3_shared import mutants as _mutants


# PROT-H25 A5 (domain-branch audit): the ops-spec helper implementations of the two domains (Round 2 pack logic). Everything else
# in src/paladin decides authority / governance / disclosure generically; the static scan must find no domain, model, body,
# principal, role or relation literal outside these directories.
DOMAIN_LOGIC_MODULES = ("src/paladin/domains/manufacturing/logic", "src/paladin/domains/project/logic")


# PROT-H28 1.3 / P1f-8 (module constants read by the harness): every module that builds an ExternalRequest, mints or stores an external
# capability, calls submit, interprets replies, retries, or reads the observer. Mutant-only adapter-side code lives in
# paladin.extgate_mut, loaded by name when (and only when) policy_gate_in_adapter is active: see PaladinVariant.adapter_modules.
ADAPTER_MODULES = ("paladin.worldbridge", "paladin.extdispatch", "paladin.extoutcome", "paladin.extoutbox")
EXTERNAL_HISTORY_PREFIXES = ("led/meta/ext/",)   # intents + outcome records (HistoryStore keys, G3-E15 tamper discovery)


class PaladinVariant:
    name = "paladin"
    audience = "paladin"  # read by the harness as type(variant).audience
    deployment_class = PaladinDeployment

    def __init__(self, mutants: Iterable[str] = ()):
        self.mutants = _mutants.validate(mutants)

    @property
    def adapter_modules(self) -> tuple:
        """ADAPTER_MODULES of THIS build (the mutant policy_gate_in_adapter adds the module holding its adapter-side rule)."""
        return ADAPTER_MODULES + (("paladin.extgate_mut",) if "policy_gate_in_adapter" in self.mutants else ())

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock,
               state_dir=None, history=None, anchor=None, governance=None, external=None, authority_source=None,
               resume=False) -> PaladinDeployment:
        return self.deployment_class(domain, world_handle_factory, verifier, ops_spec, auth_spec, clock, self.mutants,
                                     state_dir, history, anchor, governance, external, authority_source, resume)
