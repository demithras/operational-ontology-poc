"""One deployment under attack: world store, identity provider, variant Deployment, effect meter, oracle.

Every call is bracketed by two world snapshots; what happened is the DIFF, never CallResult.
"""
from __future__ import annotations

import copy
import os
import tempfile
import time

from r3_oracle import authority, ops_model
from r3_oracle.effect_meter import EffectMeter
from r3_shared.clock import LogicalClock
from r3_shared.identity import IdentityProvider
from r3_shared.variant import CallResult
from r3_shared.world import WorldStore

from .classify import classify

AUD_CANDIDATES = ("r3", "r3-deployment", "paladin", "conventional", "fake", "agent-api", "api")
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
        self.aud = self._detect_aud()
        self._tokens: dict[str, str] = {}
        self._tools: dict[str, list[str]] = {}
        self.committed: set[str] = set()
        self.n = 0

    # -- deployment / audience -------------------------------------------------------------------
    def _deploy(self):
        return self.variant.deploy(self.domain, self.store.handle_factory(), self.verifier, self.ops, self.auth,
                                   self.clock)

    def _detect_aud(self) -> str:
        declared = getattr(self.dep, "audience", None) or getattr(self.variant, "audience", None)
        if declared:
            return declared
        admin = next(p["id"] for p in self.auth["principals"] if "admin" in p["roles"])
        for aud in (getattr(self.variant, "name", None), self.domain, *AUD_CANDIDATES):
            if aud and self.dep.tools(self.idp.issue(admin, aud, TTL, self.clock)):
                return aud
        return AUD_CANDIDATES[0]

    # -- tokens ----------------------------------------------------------------------------------
    def token(self, sub: str) -> str:
        if sub not in self._tokens:
            self._tokens[sub] = self.idp.issue(sub, self.aud, TTL, self.clock)
        return self._tokens[sub]

    def tools(self, sub: str) -> list[str]:
        if sub not in self._tools:
            self._tools[sub] = [t.name for t in self.dep.tools(self.token(sub))]
        return self._tools[sub]

    def principals(self) -> list[dict]:
        return self.auth["principals"]

    def agents(self) -> list[str]:
        return [p["id"] for p in self.principals() if p["kind"] == "agent"]

    def snapshot(self) -> dict:
        return self.meter.snapshot()

    # -- authority changes -----------------------------------------------------------------------
    def set_authority(self, new_auth: dict) -> str:
        self.auth = copy.deepcopy(new_auth)
        self._tools.clear()
        fn = getattr(self.dep, "set_authority", None)
        if fn is not None:
            try:
                fn(copy.deepcopy(new_auth))
                return "set_authority"
            except TypeError:
                pass
        self.dep = self._deploy()
        return "redeploy"

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
            outcome = ops_model.evaluate(self.ops, self.auth, subject, on_behalf_of, operation, oargs, snap,
                                         self.clock.now(), frozenset(self.committed), request_id)
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

    def authorized_ops(self, sub: str) -> list[str]:
        return [o["name"] for o in self.ops["operations"] if authority.could_ever_allow(sub, o["name"], self.auth)]


def _plain(x):
    if isinstance(x, dict):
        return {str(k): _plain(dict.get(x, k)) for k in dict.keys(x)}
    if isinstance(x, (list, tuple)):
        return [_plain(i) for i in x]
    return x if isinstance(x, (str, int, float, bool)) or x is None else repr(x)
