"""ConventionalVariant: typed service + policy engine + tool surface, wired behind the neutral Variant protocol."""
from __future__ import annotations

from r3_shared.authgraph import authority_document
from r3_shared.variant import CallResult, ReplayResult, ToolDescriptor

from r3_shared import mutants as shared_mutants

from .histledger import HISTORY_LAYOUT
from .service import Service
from .tools import ToolSurface

AUDIENCE = "conventional"  # token audience this variant accepts (== variant name)


class ConventionalDeployment:
    HISTORY_LAYOUT = HISTORY_LAYOUT

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

    # -- Gate 2: delegation (PROT-H24) and provenance (PROT-H27) ---------------------------------------------
    def authority_state(self) -> dict:
        return authority_document(self.service.policy.doc)

    def delegate(self, token, edge, request_id) -> CallResult:
        return self.service.delegate(token, edge, request_id)

    def revoke(self, token, edge_id, request_id) -> CallResult:
        return self.service.revoke(token, edge_id, request_id)

    def authority_used(self, request_id) -> CallResult:
        return self.service.authority_used(request_id)

    def replay(self, decision_id) -> ReplayResult:
        return self.service.replayer.replay(decision_id)

    def explain(self, decision_id) -> ReplayResult:
        return self.service.replayer.replay(decision_id)  # same code path: no prose fallback (R27-7)

    def set_dependency_down(self, adapter: str, down: bool = True) -> None:
        (self.service.unavailable.add if down else self.service.unavailable.discard)(adapter)

    def arm_crash(self, point) -> None:
        self.service.arm_crash(point)

    def crash(self) -> None:
        self.service.crash()

    def restart(self) -> None:
        self.service.restart()


class ConventionalVariant:
    name = "conventional"
    audience = AUDIENCE

    deployment_class = ConventionalDeployment

    def __init__(self, mutants=()):
        self.mutant_switches = shared_mutants.validate(mutants)

    def deploy(self, domain, world_handle_factory, verifier, ops_spec, auth_spec, clock, state_dir=None,
               history=None, anchor=None) -> ConventionalDeployment:
        # state_dir is accepted but unused: all durable state (effects, idempotency ledger, approvals, the authority in
        # force) lives in the world DB, in the same transaction as the effects - atomic by construction. With a
        # HistoryStore (H27 runs) every record other than the world store lives there instead (histledger.py).
        return ConventionalDeployment(Service(domain, world_handle_factory, verifier, ops_spec, auth_spec, clock,
                                              AUDIENCE, self.mutant_switches, history, anchor))
