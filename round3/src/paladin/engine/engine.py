"""The Engine: one generic executor for any valid IR package (kind-based dispatch only)."""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from . import effects, outcome, provenance as prov, queries
from .authority import Principal
from .canon import digest, freeze, to_plain
from .capabilities import Minter, tool_facade
from .effects import AdapterRegistry
from .errors import InvalidRequest, LoadError, SimulatedCrash
from .journal import AppendOnlyLog, Journal
from .logic import LogicBindings
from .pipeline import TRANSITIONS
from .registry import DISPATCH_TABLE, load_model
from .snapshot import ExecutionsView, snapshot
from .store import Store

_PROV_FIELDS = ("exec", "state", "package_id", "package_version", "action", "action_version", "policy_versions",
                "principal", "inputs", "key", "gates", "approvals", "soft_flags", "effect_ids", "envelopes", "responses",
                "observed", "updated_at")

ENGINE_VERSION = "1.2"  # v1.1: snapshot returns + journaled gate-pass check; v1.2: Engine-owned provenance envelope
# (docs/engine_semantics.md sections 8 and 9)


def utc_clock() -> str:
    return datetime.now(timezone.utc).isoformat()


def required_bindings(package: dict) -> list:
    """Every logic/adapter reference the package needs (Unbound items), without building an Engine."""
    return list(dict.fromkeys(load_model(package).required))


class Engine:
    def __init__(self, package: dict, bindings: Optional[LogicBindings] = None, adapters: Any = None,
                 journal: Any = None, clock: Optional[Callable[[], str]] = None, faults: Iterable[str] = ()):
        self.model = load_model(package)
        self.bindings = bindings if bindings is not None else LogicBindings()
        self.adapters = adapters if isinstance(adapters, AdapterRegistry) else AdapterRegistry(adapters)
        missing = [u for u in dict.fromkeys(self.model.required)
                   if (u.kind == "adapter" and self.adapters.lookup(*u.key.split(":", 1)) is None)
                   or (u.kind != "adapter" and not self.bindings.has(u.kind, u.key))]
        if missing:
            raise LoadError(missing)
        self.minter = Minter()
        self.store = Store(self.model, self.minter.verifier())
        self.journal = journal if isinstance(journal, Journal) else Journal(journal)
        self.effect_log, self.provenance = AppendOnlyLog(), AppendOnlyLog()
        self._executions: dict[str, dict] = {}  # internal; callers read snapshots via .executions
        self.idempotency: dict[str, str] = {}
        self.directory: dict[str, Principal] = {}
        self._clock = clock or utc_clock
        self._faults = set(faults)
        for rec in self.journal:
            self._absorb(rec, replay=True)

    # ---- plumbing -----------------------------------------------------------------------
    def now(self) -> str:
        return self._clock()

    def state(self):
        return self.store.current

    def read_view(self, state=None):
        def state_of():
            return state if state is not None else self.store.current
        view = None

        def call(fid: str, args: dict | None = None):
            return self.dispatch("functions", "call", fid, args=dict(args or {}), state=state_of(), view=view)
        view = queries.make_read_view(state_of, call)
        return view

    def dispatch(self, kind: str, op: str, rid: Optional[str] = None, **kw):
        handler = DISPATCH_TABLE.get(kind)
        if handler is None or op not in handler.ops:
            raise InvalidRequest(f"no operation {op!r} for kind {kind!r}")
        spec = None
        if rid is not None:
            spec = self.model.get(kind, rid)
            if spec is None:
                raise InvalidRequest(f"unknown {kind} {rid!r}")
        return handler.ops[op](self, spec, **kw)

    @staticmethod
    def parse_ref(k: str) -> tuple:
        return tuple(ast.literal_eval(k))

    def fingerprint(self) -> str:
        return digest({"store": self.store.current.snapshot(), "executions": self._executions,
                       "effects": self.effect_log.entries(), "provenance": self.provenance.entries()})

    # ---- identity -----------------------------------------------------------------------
    def register_principal(self, p: Principal) -> None:
        if p.delegated_by is not None and self.directory.get(p.delegated_by.pid) != p.delegated_by:
            raise InvalidRequest(f"delegator {p.delegated_by.pid!r} is not registered with these claims")
        self._write({"kind": "principal", "principal": p.to_plain()})

    def principal_of(self, pid: str) -> Principal:
        return self.directory[pid]

    def identify(self, presented: Any) -> tuple[Optional[Principal], str]:
        pid = presented if isinstance(presented, str) else getattr(presented, "pid", None)
        reg = self.directory.get(pid) if isinstance(pid, str) else None
        if reg is None:
            return None, f"unknown principal {pid!r}"
        if isinstance(presented, Principal) and presented != reg:
            # P2a patch V1 (request-scoped delegation): a presented principal may carry a delegated_by chain that the
            # directory does not hold, provided EVERY chain element is registered with exactly the presented claims.
            if not self._chain_registered(presented):
                return None, "presented claims differ from the registered identity"
            return presented, ""
        if not isinstance(presented, (str, Principal)):
            return None, "unsupported principal object"
        return reg, ""

    def _chain_registered(self, p: Principal) -> bool:
        """P2a patch V1: p's own claims and every delegator's claims equal the registered claims of that pid."""
        seen = set()
        while p is not None:
            reg = self.directory.get(p.pid)
            if reg is None or p.pid in seen or (p.roles, p.relations) != (reg.roles, reg.relations):
                return False
            seen.add(p.pid)
            p = p.delegated_by
        return True

    # ---- seeding (before any execution) --------------------------------------------------
    def seed(self, ops: list) -> None:
        if self._executions:
            raise InvalidRequest("seeding is closed once an action has been proposed")
        sid = f"seed:{len(self.journal)}"
        grant = self.minter.mint(sid)
        try:
            self.store.apply(grant, sid, to_plain(ops))
        finally:
            self.minter.revoke(grant)
        self._write({"kind": "seed", "seed": sid, "ops": ops}, applied=True)

    # ---- journaling ----------------------------------------------------------------------
    def _write(self, rec: dict, applied: bool = False) -> dict:
        r = self.journal.append({**rec, "engine_version": ENGINE_VERSION})
        self._absorb(r, replay=False, applied=applied)
        return r

    def _absorb(self, r: dict, replay: bool, applied: bool = False) -> None:
        kind = r["kind"]
        if kind == "principal":
            p = Principal.from_plain(r["principal"])
            self.directory[p.pid] = p
        elif kind in ("seed", "exec") and replay:
            ops = r.get("ops") if kind == "seed" else (r.get("commit") or {}).get("ops")
            if ops:
                sid = f"replay:{r['seq']}"
                grant = self.minter.mint(sid)
                try:
                    self.store.apply(grant, sid, ops)
                finally:
                    self.minter.revoke(grant)
        if kind == "exec":
            snap = r["rec"]
            if replay:
                self._executions[snap["exec"]] = to_plain(snap)
                if snap["key"] is not None and not snap["key_conflict"]:
                    self.idempotency[f"{snap['action']}\x1f{snap['key']}"] = snap["exec"]
            for e in (r.get("commit") or {}).get("entries", []):
                self.effect_log.append(e)
            self.provenance.append({**{k: snap.get(k) for k in _PROV_FIELDS}, "note": r.get("note"),
                                    "engine_version": r.get("engine_version")})
        elif kind in ("seed", "retry", "attempt"):
            self.provenance.append({k: v for k, v in r.items() if k != "ops"})

    def new_execution(self, spec, inputs: dict, pid: Any, key: Optional[str], intent: str,
                      expected_versions: Optional[dict] = None, presented: Any = None) -> dict:
        xid = f"x{len(self._executions) + 1}"
        conflict = key is not None and f"{spec.rid}\x1f{key}" in self.idempotency
        policy_versions = {pid_: self.model.get("policies", pid_).version for _t, pid_ in spec.policy_refs if pid_}
        rec = {"exec": xid, "action": spec.rid, "action_version": spec.version, "package_id": self.model.package_id,
               "package_version": self.model.version, "principal": {"pid": pid}, "inputs": inputs, "key": key,
               "key_conflict": conflict, "digest": intent, "expected_versions": dict(expected_versions or {}), "presented": presented, "state": None, "history": [], "gates": [],
               "policy_versions": policy_versions, "approvals": [], "base_versions": {}, "soft_flags": [],
               "intents": [], "envelopes": {}, "responses": {}, "adapter_errors": [], "observations": [], "rejected_observations": [],
               "effect_ids": [], "observed": None, "created_at": self.now(), "updated_at": None}
        self._executions[xid] = rec
        if key is not None and not conflict:
            self.idempotency[f"{spec.rid}\x1f{key}"] = xid
        return self.record(rec, "PROPOSED")

    def record(self, rec: dict, state: str, note: Optional[str] = None, commit: Optional[dict] = None,
               fault: Optional[str] = None) -> dict:
        if state not in TRANSITIONS.get(rec["state"], set()):
            raise InvalidRequest(f"illegal transition {rec['state']} -> {state} for {rec['exec']}")
        if rec["state"] != state:
            rec["history"].append(state)
        rec["state"], rec["updated_at"] = state, self.now()
        self._write({"kind": "exec", "rec": rec, "commit": commit, "note": note})
        point = fault or state
        if point in self._faults:
            raise SimulatedCrash(f"crash after {point} of {rec['exec']}")
        return rec

    def note_retry(self, rec: dict) -> None:
        self._write({"kind": "retry", "exec": rec["exec"], "at": self.now()})

    def note_attempt(self, rec: dict, who: Any, why: str) -> None:
        self._write({"kind": "attempt", "exec": rec["exec"], "who": who if isinstance(who, str) else
                     getattr(who, "pid", repr(who)), "why": why, "at": self.now()})

    def envelope(self, rec: dict, spec, eff) -> "prov.ProvenanceEnvelope":
        """The provenance envelope of one adapter-routed effect (a pure function of the execution record)."""
        return prov.build_envelope(rec, spec, eff, [e for e in spec.effects if effects.routes_to_adapter(e)], ENGINE_VERSION)

    def call_adapter(self, grant, rec: dict, spec, eff, payload: dict, envelope=None):
        self.minter.verifier()(grant, rec["exec"])
        adapter = self.adapters.lookup(eff.operation, eff.target)
        env = envelope if envelope is not None else self.envelope(rec, spec, eff)
        return adapter.apply(effects.effect_request(rec["exec"], spec, eff, rec["key"], env), freeze(payload))

    # ---- public API ----------------------------------------------------------------------
    def propose(self, action_id: str, inputs: dict, principal: Any, idempotency_key: Optional[str] = None,
                expected_versions: Optional[dict] = None) -> dict:
        return snapshot(self.dispatch("actions", "propose", action_id, inputs=inputs, principal=principal,
                                      idempotency_key=idempotency_key, expected_versions=expected_versions))

    def _decide(self, op: str, execution: str, approver: Any) -> dict:
        rec = self._executions.get(execution)
        if rec is None:
            raise InvalidRequest(f"unknown execution {execution!r}")
        return snapshot(self.dispatch("actions", op, rec["action"], execution=execution, approver=approver))

    def approve(self, execution: str, approver: Any) -> dict:
        return self._decide("approve", execution, approver)

    def reject(self, execution: str, approver: Any) -> dict:
        return self._decide("reject", execution, approver)

    def reconcile(self, execution: str) -> dict:
        rec = self._executions[execution]
        return snapshot(self.dispatch("actions", "reconcile", rec["action"], execution=execution))

    def recover(self) -> list:
        return snapshot(outcome.recover(self))

    @property
    def executions(self) -> ExecutionsView:
        """Read-only view: execution id -> immutable snapshot of that record (never the live record)."""
        live = self._executions
        return ExecutionsView(lambda xid: live[xid], lambda: list(live))

    def call_function(self, function_id: str, args: dict, principal: Any = None):
        if principal is not None and self.identify(principal)[0] is None:
            raise InvalidRequest(f"unknown principal {principal!r}")
        return self.dispatch("functions", "call", function_id, args=dict(args))

    def get(self, type_id: str, key: Any):
        kind = "interfaces" if type_id in self.model.all("interfaces") else "object_types"
        if kind == "interfaces":
            return queries.get(self.state(), type_id, key)
        return self.dispatch(kind, "get", type_id, key=key)

    def interface_query(self, iface: str):
        return self.dispatch("interfaces", "query", iface)

    def tool(self, principal_id: str):
        return tool_facade(self, principal_id)
