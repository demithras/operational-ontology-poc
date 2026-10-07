"""The Variant protocol: the ONLY way the harness touches a variant. Describes WHAT, never HOW.

CallResult is never trusted by the meter: effects are measured from the world store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Protocol, runtime_checkable

from .anchor import AnchorClient
from .clock import LogicalClock
from .histstore import HistoryStore
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


@dataclass(frozen=True)
class ReplayResult:
    """PROT-H27 s6. artifacts: digest -> bytes, only when status == VERIFIED (envelope is then non-None)."""
    status: Literal["VERIFIED", "TAMPERED", "UNRESOLVED"]
    reason: str
    envelope: dict | None = None
    artifacts: dict[str, bytes] = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in ("VERIFIED", "TAMPERED", "UNRESOLVED"):
            raise ValueError(f"bad replay status {self.status!r}")


WorldHandleFactory = Callable[[str], WorldHandle]


@runtime_checkable
class Deployment(Protocol):
    """Thread safety (PROT-H23-A8): call_tool/direct/approve/read may be called concurrently from threads.
    Concurrent callers never create a forbidden effect and never commit the same request_id twice; refusing a
    concurrent legitimate request with UNAVAILABLE is safe but counted as lost progress."""

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

    def arm_crash(self, point: Literal["before_commit", "after_commit"]) -> None:
        """PROT-H23-A8: the NEXT mutating request (call_tool, direct, approve) crashes at `point`.
        before_commit = after authorization/validation, before any world write.
        after_commit = after the world commit, before the result is returned or any post-commit bookkeeping.
        That call returns CallResult("UNKNOWN", {"reason": "crashed"}); afterwards every call returns
        CallResult("UNAVAILABLE", {"reason": "crashed"}) until restart()."""

    def crash(self) -> None:
        """Crash immediately (between requests). Everything in memory is lost; the world store and state_dir survive."""

    def restart(self) -> None:
        """Rebuild from the world store + state_dir ONLY. A committed request_id never produces a second effect."""

    # ---- Gate 2 (PROTOCOL-P1d P1d-4). A variant that has not built these raises
    # NotImplementedError("not implemented yet - G2"); the harness labels that `unsupported` (verdict INCONCLUSIVE).
    def delegate(self, token: str, edge: dict, request_id: str) -> CallResult:
        """PROT-H24 s2. OK body {"edge_id"}. Mutating: thread-safe, arm_crash applies, request_id idempotent (R5)."""

    def revoke(self, token: str, edge_id: str, request_id: str) -> CallResult:
        """PROT-H24 s5. Mutating, same rules as delegate."""

    def authority_used(self, request_id: str) -> CallResult:
        """PROT-H24 R24-6. OK body {"authority_version","world_seq","tick","path":[edge ids],"on_behalf_of"};
        INVALID {"reason": "unknown_request"} if the request_id never committed."""

    def replay(self, decision_id: str) -> ReplayResult:
        """PROT-H27 s6: verify the decision's provenance against the anchor on a FRESH deployment."""

    def explain(self, decision_id: str) -> ReplayResult:
        """PROT-H27 R27-7: equals replay's verified envelope or carries the same TAMPERED/UNRESOLVED status."""


@runtime_checkable
class Variant(Protocol):
    name: str

    def __init__(self, mutants: Iterable[str] = ()) -> None:
        """Mutants (r3_shared.mutants) are activated only here, validated with mutants.validate; no global state."""

    def deploy(self, domain: str, world_handle_factory: WorldHandleFactory, verifier: TokenVerifier,
               ops_spec: dict, auth_spec: dict, clock: LogicalClock,
               state_dir: str | None = None, history: HistoryStore | None = None,
               anchor: AnchorClient | None = None) -> Deployment:
        """state_dir: a private directory that survives crash()/restart() (the world store survives too);
        everything held in memory is lost on crash.
        history (H27 runs): every durable variant record other than the world store (envelopes, receipts, artifacts,
        approvals, idempotency ledger, authority versions) lives in it and state_dir is then None. anchor None ->
        H27 APIs return UNRESOLVED `no_anchor`. Both None = H23/H24 behaviour, unchanged."""


G2_METHODS = ("delegate", "revoke", "authority_used", "replay", "explain")
G2_MISSING = "not implemented yet - G2"


def g2_call(deployment, method: str, *args, **kwargs):
    """Harness entry for the Gate 2 methods: a deployment that lacks one (variant not built yet) raises
    NotImplementedError("not implemented yet - G2"), which the harness labels `unsupported` (never SUPPORTED)."""
    if method not in G2_METHODS:
        raise ValueError(f"not a Gate 2 method: {method}")
    fn = getattr(deployment, method, None)
    if not callable(fn):
        raise NotImplementedError(G2_MISSING)
    return fn(*args, **kwargs)
