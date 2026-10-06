"""One deployment under attack: world store, identity provider, variant Deployment, effect meter, oracle.

Every call is bracketed by two world snapshots; what happened is the DIFF, never CallResult.
"""
from __future__ import annotations

import copy
import os
import tempfile
import time

from r3_oracle import approvals, authority, ops_model
from r3_oracle.effect_meter import EffectMeter
from r3_shared.clock import LogicalClock
from r3_shared.identity import IdentityProvider
from r3_shared.variant import CallResult
from r3_shared.world import WorldStore

from .classify import classify

TTL = 10 ** 6


class Env:
    def __init__(self, variant, domain: str, ops_spec: dict, auth_spec: dict, tag: str = "env"):
        self.variant, self.domain, self.ops, self.tag = variant, domain, ops_spec, tag
        self.last_result = None
        self.auth = copy.deepcopy(auth_spec)
        self.dir = tempfile.mkdtemp(prefix="h23-")
        self.store = WorldStore(os.path.join(self.dir, "world.db"))
        h = self.store.handle("harness-seed")
        with h.transaction():
            for o in ops_spec["seed"]["objects"]:
                h.create(o["type"], o["key"], o["props"])
            for lk in ops_spec["seed"]["links"]:
                h.link(lk["link_type"], lk["src"], lk["dst"])
        h.close()
        self.clock = LogicalClock(0)
        self.idp = IdentityProvider(f"h23-secret-{tag}")
        self.verifier = self.idp.verifier()
        self.reader = self.store.reader()
        self.meter = EffectMeter(self.reader)
        self.writers = {w for a in auth_spec["service_accounts"] for w in a["world_writers"]}
        self.dep = self._deploy()
        self.aud = self._declared_aud()
        self._tokens: dict[str, str] = {}
        self._tools: dict[str, list[str]] = {}
        self.committed: set[str] = set()
        self.authority_log: list[dict] = []
        self.approvals: dict[str, int] = {}
        self.n = 0

    # -- deployment / audience -------------------------------------------------------------------
    def _deploy(self):
        return self.variant.deploy(self.domain, self.store.handle_factory(), self.verifier, self.ops, self.auth,
                                   self.clock)

    def _declared_aud(self) -> str:
        """Token audience = class attribute `audience` of the variant (protocol P1b). No auto-detection."""
        aud = getattr(type(self.variant), "audience", None)
        if not isinstance(aud, str) or not aud:
            raise RuntimeError(f"variant {type(self.variant).__name__} defines no class attribute `audience`; "
                               "the harness does not guess token audiences")
        return aud

    def safe_tools(self, token) -> list:
        """tools() for any token; a variant that raises on a token it rejects is treated as listing nothing."""
        try:
            return list(self.dep.tools(token))
        except Exception:  # noqa: BLE001
            return []

    # -- tokens ----------------------------------------------------------------------------------
    def token(self, sub: str) -> str:
        if sub not in self._tokens:
            self._tokens[sub] = self.idp.issue(sub, self.aud, TTL, self.clock)
        return self._tokens[sub]

    def tools(self, sub: str) -> list[str]:
        if sub not in self._tools:
            self._tools[sub] = [t.name for t in self.safe_tools(self.token(sub))]
        return self._tools[sub]

    def principals(self) -> list[dict]:
        return self.auth["principals"]

    def agents(self) -> list[str]:
        return [p["id"] for p in self.principals() if p["kind"] == "agent"]

    def snapshot(self) -> dict:
        return self.meter.snapshot()

    # -- authority changes -----------------------------------------------------------------------
    def set_authority(self, new_auth: dict) -> dict:
        """Authority changes go ONLY through Deployment.set_authority (no fallback). Returns the version log."""
        before = self.dep.authority_version()
        self.dep.set_authority(copy.deepcopy(new_auth))
        self.auth = copy.deepcopy(new_auth)
        self._tools.clear()
        after = self.dep.authority_version()
        entry = {"before": before, "after": after}
        self.authority_log.append(entry)
        return entry

    # -- the one way a call is made --------------------------------------------------------------
    def call(self, *, rule: str, via: str, token: str, subject: str | None, operation: str, args,
             on_behalf_of: str | None = None, request_id: str | None = None, tags=(), clean=False,
             backstop_probe=False, args_for_oracle=None) -> dict:
        """Run one call, measure it, judge it. `subject` is the VERIFIED subject the token should resolve to
        (None for tokens that must not verify)."""
        self.n += 1
        snap = self.snapshot()
        oargs = args if args_for_oracle is None else args_for_oracle
        if subject is None:
            outcome = ops_model.Outcome(ops_model.DENIED_AUTHORITY, detail="token does not verify")
        else:
            akey = approvals.key(subject, on_behalf_of, operation, oargs)
            outcome = ops_model.evaluate(self.ops, self.auth, subject, on_behalf_of, operation, oargs, snap,
                                         self.clock.now(), frozenset(self.committed), request_id,
                                         approved=self.approvals.get(akey, 0) > 0)
            if outcome.used_approval and outcome.effects:
                self.approvals[akey] -= 1  # single use: the oracle consumes it when a correct system commits
        fn = self.dep.call_tool if via == "call_tool" else self.dep.direct
        t0 = time.perf_counter()
        res: CallResult | None = None
        err = None
        self.meter.begin()
        try:
            res = fn(token, operation, args, on_behalf_of, request_id)
        except Exception as exc:  # noqa: BLE001 - an exception from a variant is data, not a harness crash
            err = f"{type(exc).__name__}: {exc}"
        measured = self.meter.end()
        dt = (time.perf_counter() - t0) * 1000.0
        self.last_result = res
        status = "EXCEPTION" if res is None else res.status
        if measured and request_id is not None:
            self.committed.add(request_id)
        rec = classify(outcome, measured, status, writers=self.writers, via=via, tags=set(tags), clean=clean,
                       backstop_probe=backstop_probe)
        rec.update({"rule": rule, "via": via, "subject": subject, "operation": operation, "args": _plain(args),
                    "on_behalf_of": on_behalf_of, "request_id": request_id, "status": status, "error": err,
                    "latency_ms": dt, "oracle": outcome.kind, "oracle_detail": outcome.detail,
                    "in_tools": operation in self.tools(subject) if subject else None})
        return rec

    def approve(self, *, rule: str, token: str, approver: str | None, requester: str | None, operation: str, args,
                on_behalf_of: str | None = None, tags=()) -> dict:
        """Pre-approve the exact request via Deployment.approve. Oracle: valid approvals enter the ledger. An
        approval must change nothing in the canonical world (any diff is a forbidden effect); whether a bad approval
        was wrongly honoured shows when the request is committed."""
        self.n += 1
        valid, why = approvals.validate(self.ops, self.auth, approver, requester, operation, args)
        outcome = ops_model.Outcome(ops_model.COMMIT if valid else ops_model.DENIED_AUTHORITY, detail=why)
        res, err = None, None
        t0 = time.perf_counter()
        self.meter.begin()
        try:
            res = self.dep.approve(token, operation, copy.deepcopy(args), requester or "?", on_behalf_of)
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
        measured = self.meter.end()
        dt = (time.perf_counter() - t0) * 1000.0
        if valid:
            k = approvals.key(requester, on_behalf_of, operation, args)
            self.approvals[k] = self.approvals.get(k, 0) + 1
        status = "EXCEPTION" if res is None else res.status
        rec = classify(outcome, measured, status, writers=self.writers, via="approve", tags=set(tags), clean=False,
                       backstop_probe=False)
        rec.update({"rule": rule, "via": "approve", "subject": approver, "operation": operation,
                    "args": _plain(args), "on_behalf_of": on_behalf_of, "request_id": None, "status": status,
                    "error": err, "latency_ms": dt, "oracle": "APPROVAL_VALID" if valid else "APPROVAL_INVALID",
                    "oracle_detail": why, "in_tools": None, "requester": requester})
        return rec

    def close(self) -> None:
        import shutil
        try:
            self.reader.close()
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)

    def authorized_ops(self, sub: str) -> list[str]:
        return [o["name"] for o in self.ops["operations"] if authority.could_ever_allow(sub, o["name"], self.auth)]


def _plain(x):
    if isinstance(x, dict):
        return {str(k): _plain(dict.get(x, k)) for k in dict.keys(x)}
    if isinstance(x, (list, tuple)):
        return [_plain(i) for i in x]
    return x if isinstance(x, (str, int, float, bool)) or x is None else repr(x)
