"""The Variant protocol: the ONLY way the harness touches a variant. Describes WHAT, never HOW.

CallResult is never trusted by the meter: effects are measured from the world store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Protocol, runtime_checkable

from .clock import LogicalClock
from .identity import TokenVerifier
from .world import WorldHandle

Status = Literal["OK", "DENIED", "INVALID", "UNAVAILABLE", "UNKNOWN"]
STATUSES = ("OK", "DENIED", "INVALID", "UNAVAILABLE", "UNKNOWN")


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CallResult:
    """Body convention: every non-OK result carries a string body["reason"]."""
    status: Status
    body: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"bad status {self.status!r}")


WorldHandleFactory = Callable[[str], WorldHandle]


@runtime_checkable
class Deployment(Protocol):
    def tools(self, token: str) -> list[ToolDescriptor]:
        """The agent-facing surface visible to this token's subject."""

    def call_tool(self, token: str, name: str, args: dict, on_behalf_of: str | None = None,
                  request_id: str | None = None) -> CallResult: ...

    def direct(self, token: str, operation: str, args: dict, on_behalf_of: str | None = None,
               request_id: str | None = None) -> CallResult:
        """The layer under the tools (Paladin's Engine entry / the conventional service API): backstop attack surface."""

    def read(self, token: str, operation: str, args: dict) -> CallResult: ...

    def approve(self, token: str, operation: str, args: dict, requester: str,
                on_behalf_of: str | None = None) -> CallResult:
        """The token's subject pre-approves the EXACT request (requester, on_behalf_of, operation, canonicalised args).
        A later call_tool/direct of that exact request by `requester` may then commit; any difference in inputs needs
        a new approval. One approval authorises at most one commit. Approver rules (auth spec semantics): a different
        principal, outside the requester's delegation chain, holding the approval operation on the resources.
        A request that needs approval and has none -> CallResult("DENIED", {"reason": "approval_required"}), zero effects."""

    def set_authority(self, auth_spec: dict) -> None:
        """Replace the authority spec in force; later requests (incl. replays) are decided against it."""

    def authority_version(self) -> str:
        """sha256 hex of the canonical JSON (sorted keys, compact separators) of the spec in force."""

    def crash(self) -> None:
        """Simulate process crash (may raise NotImplementedError until H29)."""

    def restart(self) -> None:
        """Recover from crash (may raise NotImplementedError until H29)."""


@runtime_checkable
class Variant(Protocol):
    name: str

    def __init__(self, mutants: Iterable[str] = ()) -> None:
        """Mutants (r3_shared.mutants) are activated only here, validated with mutants.validate; no global state."""

    def deploy(self, domain: str, world_handle_factory: WorldHandleFactory, verifier: TokenVerifier,
               ops_spec: dict, auth_spec: dict, clock: LogicalClock) -> Deployment: ...
