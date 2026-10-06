"""ConventionalVariant: typed service + policy engine + tool surface, wired behind the neutral Variant protocol."""
from __future__ import annotations

from r3_shared.variant import CallResult, ToolDescriptor

from r3_shared import mutants as shared_mutants

from .service import Service
from .tools import ToolSurface

AUDIENCE = "conventional"  # token audience this variant accepts (== variant name)


class ConventionalDeployment:
    def __init__(self, service: Service):
        self.service, self._tools = service, ToolSurface(service)

    def tools(self, token: str) -> list[ToolDescriptor]:
        return self._tools.tools(token)

    def call_tool(self, token, name, args, on_behalf_of=None, request_id=None) -> CallResult:
        return self._tools.call_tool(token, name, args, on_behalf_of, request_id)

    def direct(self, token, operation, args, on_behalf_of=None, request_id=None) -> CallResult:
        # the service API under the tool layer: the backstop attack surface (R2)
        skip = self.service.mutant("backstop_bypass")  # BUG when on: the PDP decision is skipped on this path
        return self.service.execute(token, operation, args, on_behalf_of, request_id, _enforce=not skip)

    def read(self, token, operation, args) -> CallResult:
        return self.service.read(token, operation, args)

    # -- operations beyond the neutral protocol (used by tests / harness drivers that know this variant) -----
    def set_authority(self, auth_spec: dict) -> None:
        """Install a new authority version; every later decision (including replays) uses it."""
        self.service.set_authority(auth_spec)

    def authority_version(self) -> str:
        return self.service.policy.digest

    def approve(self, token, operation, args, requester, on_behalf_of=None) -> CallResult:
        return self.service.approve(token, operation, args, requester, on_behalf_of)

    def set_dependency_down(self, adapter: str, down: bool = True) -> None:
        (self.service.unavailable.add if down else self.service.unavailable.discard)(adapter)

    def crash(self) -> None:
        raise NotImplementedError("crash/restart arrive with H29")

    def restart(self) -> None:
        raise NotImplementedError("crash/restart arrive with H29")


class ConventionalVariant:
    name = "conventional"

    deployment_class = ConventionalDeployment

    def __init__(self, mutants=()):
        self.mutant_switches = shared_mutants.validate(mutants)

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock) -> ConventionalDeployment:
        return ConventionalDeployment(Service(domain, world_handle_factory, verifier, ops_spec, auth_spec, clock,
                                              AUDIENCE, self.mutant_switches))
