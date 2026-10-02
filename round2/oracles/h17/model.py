"""H17 oracle: a pure reference transition model of a governed world.

Allowed imports: stdlib only. Never eoo_engine, eoo_toolchain, domains/*/logic (static test + evaluator check).

World = (canonical, committed, external, executions, idempotency index, adapter mode).
  canonical  version of the canonical store; only an Action effect on a LOCAL type could bump it (none is declared by
             the two registered domains, so it must stay 0 forever)
  committed  entries in the EffectLog (committed business effects)
  external   effects that really exist in the external system (adapter ground truth)

Transitions
  READ transitions (read, function_call, observe_outcome-without-new-effect): the world is never modified.
  WRITE transitions exist ONLY inside an Action execution and need explicit GATE TOKENS (identity, request, inputs,
  fresh, authority, preconditions, policy, and an approval for policy=approval). The tokens are facts the scenario
  author states about a request; the oracle never computes them from domain logic.
"""
from dataclasses import dataclass, field

GATE_ORDER = ("identity", "request", "inputs", "fresh", "authority", "preconditions", "policy")
DENIED, PENDING, INFLIGHT, DONE, UNKNOWN = "DENIED", "PENDING", "INFLIGHT", "DONE", "UNKNOWN"
PROPOSED_STATE = "PROPOSED"
CRASH_POINTS = ("PROPOSED", "APPROVED", "EXECUTING", "ext_intent", "ext_response", "EFFECTS_COMMITTED")
ADAPTER_MODES = ("ok", "timeout", "commit_no_response")


@dataclass(frozen=True)
class Req:
    action: str
    intent: str  # opaque identity of (action, inputs, principal)
    key: str | None
    tokens: dict  # gate -> bool, plus "policy" -> "allow" | "approval" | "deny"
    n_effects: int


@dataclass
class Exec:
    req: Req
    state: str
    ext: int = 0  # external effects this execution produced so far
    com: int = 0  # EffectLog entries this execution produced
    denied_at: str | None = None
    conflict: bool = False
    crash: str | None = None


@dataclass
class World:
    canonical: int = 0
    committed: int = 0
    external: int = 0
    mode: str = "ok"
    execs: list = field(default_factory=list)  # index = oracle exec id
    keys: dict = field(default_factory=dict)  # (action, key) -> exec id

    # ---- READ transitions: identity on the world -------------------------------------------------
    def read(self) -> None:
        return None

    def function_call(self) -> None:
        return None

    # ---- WRITE transitions: only through the Action lifecycle ------------------------------------
    def first_failed_gate(self, req: Req):
        for g in GATE_ORDER[:-1]:
            if not req.tokens.get(g, True):
                return g
        return "policy" if req.tokens.get("policy") == "deny" else None

    def _decide(self, x: Exec) -> None:
        g = self.first_failed_gate(x.req)
        if g is not None:
            x.state, x.denied_at = DENIED, g
        elif x.req.tokens.get("policy") == "approval":
            x.state = PENDING
        else:
            self._run(x)

    def _run(self, x: Exec) -> None:
        """Execute (or resume) an approved execution. Effects already answered by the adapter are never called again."""
        n = x.req.n_effects
        if x.ext < n and self.mode == "timeout":
            x.state = UNKNOWN
        elif x.ext < n and self.mode == "commit_no_response":
            x.ext += 1
            self.external += 1
            x.state = UNKNOWN
        else:
            self.external += n - x.ext
            self.committed += n - x.com
            x.ext, x.com, x.state = n, n, DONE

    def propose(self, req: Req, crash: str | None = None) -> int:
        """Returns the oracle exec id. A retry (same key, same intent) returns the existing id and changes nothing."""
        prior = self.keys.get((req.action, req.key)) if req.key is not None else None
        if prior is not None and self.execs[prior].req.intent == req.intent and not self.execs[prior].conflict:
            return prior
        x = Exec(req, PROPOSED_STATE)
        self.execs.append(x)
        oid = len(self.execs) - 1
        if prior is not None:  # same key, different intent: denied before anything else
            x.state, x.denied_at, x.conflict = DENIED, "idempotency", True
            return oid
        if req.key is not None:
            self.keys[(req.action, req.key)] = oid
        if crash is None:
            self._decide(x)
        else:
            self._crash(x, crash)
        return oid

    def _crash(self, x: Exec, point: str) -> None:
        """The process died right after the journal record of ``point``. Only what already happened is visible."""
        x.state = INFLIGHT
        if point == "ext_response":
            x.ext += 1
            self.external += 1
        elif point == "EFFECTS_COMMITTED":
            self.external += x.req.n_effects
            self.committed += x.req.n_effects
            x.ext, x.com = x.req.n_effects, x.req.n_effects
        x.crash = point

    def recover(self) -> None:
        for x in self.execs:
            if x.state != INFLIGHT:
                continue
            point = x.crash or "PROPOSED"
            if point == "PROPOSED":
                self._decide(x)
            elif point == "ext_intent":
                x.state = UNKNOWN  # never re-called blindly
            elif point == "EFFECTS_COMMITTED":
                x.state = DONE
            else:
                self._run(x)

    def approve(self, oid: int, approver_ok: bool) -> None:
        x = self.execs[oid]
        if x.state == PENDING and approver_ok:
            self._run(x)

    def reject(self, oid: int, approver_ok: bool) -> None:
        x = self.execs[oid]
        if x.state == PENDING and approver_ok:
            x.state, x.denied_at = DENIED, "approval"

    def observe_outcome(self, oid: int) -> None:
        """Observation never changes the world; it can only classify an uncertain execution that really happened."""
        x = self.execs[oid]
        if x.state == UNKNOWN and x.ext > 0:
            x.state = DONE
        elif x.state == INFLIGHT and x.crash == "EFFECTS_COMMITTED":
            x.state = DONE  # effects were already committed before the crash; only the outcome is classified now

    def force_execute(self, oid: int) -> None:
        """Executing an execution that is not approved/in-flight is refused; the world is unchanged."""
        return None

    def set_mode(self, mode: str) -> None:
        assert mode in ADAPTER_MODES
        self.mode = mode

    # ---- observation ----------------------------------------------------------------------------
    def classes(self) -> list:
        return [x.state for x in self.execs]

    def marker(self) -> tuple:
        return (self.canonical, self.committed, self.external)

