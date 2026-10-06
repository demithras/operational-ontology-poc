"""Test-only H23 fakes (never registered). They reuse the oracle's rules, so a "correct" fake is correct BY
CONSTRUCTION and exists to prove the harness can say SUPPORTED; the broken fakes prove it says REJECTED/not SUPPORTED.

modes: correct | allow-all | direct-open (tools hide, direct skips authz) | deny-all
The fakes honour the four H23 mutants through their own frozen constructor set (`FakeVariant(mode, mutants)`) so the mutation proof can be tested.
"""
from __future__ import annotations

import copy

from r3_oracle import approvals as oracle_approvals
from r3_oracle import authority, ops_model
from r3_shared import mutants as mutants_mod
from r3_shared.identity import TokenError
from r3_shared.variant import CallResult, ToolDescriptor
from r3_shared.world import WorldConflict


class FakeDep:
    audience = "fake"

    def __init__(self, mode, domain, factory, verifier, ops, auth, clock, mutants=frozenset()):
        self.mutants = mutants
        self.mode, self.domain, self.f, self.verifier = mode, domain, factory, verifier
        self.ops, self.auth, self.clock = ops, auth, clock
        self.world, self.done, self.approved = factory("fake-service"), {}, {}
        self.admin = next(p["id"] for p in auth["principals"] if "admin" in p["roles"])

    def _m(self, name):
        return name in self.mutants

    def authority_version(self):
        import hashlib
        import json
        return hashlib.sha256(json.dumps(self.auth, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def set_authority(self, auth):
        self.auth = copy.deepcopy(auth)

    def _sub(self, token):
        try:
            return self.verifier.verify(token, self.audience, self.clock)
        except TokenError:
            return None

    def tools(self, token):
        sub = self._sub(token)
        if sub is None or self.mode == "deny-all":
            return []
        every = self.mode == "allow-all" or self._m("tool_overexposure")
        return [ToolDescriptor(o["name"], {}) for o in self.ops["operations"]
                if every or authority.could_ever_allow(sub, o["name"], self.auth)]

    def call_tool(self, token, name, args, on_behalf_of=None, request_id=None):
        if name not in {t.name for t in self.tools(token)}:
            return CallResult("UNKNOWN", {})
        return self._run(token, name, args, on_behalf_of, request_id, backstop=False)

    def direct(self, token, operation, args, on_behalf_of=None, request_id=None):
        return self._run(token, operation, args, on_behalf_of, request_id, backstop=True)

    def _run(self, token, op, args, obo, rid, backstop):
        sub = self._sub(token)
        if sub is None or self.mode == "deny-all":
            return CallResult("DENIED", {"reason": "no"})
        if not isinstance(args, dict):
            return CallResult("INVALID", {})
        held = args
        args = {k: held[k] for k in list(held.keys())}  # copy once at entry
        if self._m("identity_substitution") and isinstance(args.get("principal"), str):
            sub = args["principal"]
        skip = self.mode == "allow-all" or (self.mode == "direct-open" and backstop) \
            or (backstop and self._m("backstop_bypass"))
        if rid is not None and rid in self.done:
            return self.done[rid]
        subj = self.admin if skip else sub
        snap = self.world_snapshot()
        akey = oracle_approvals.key(sub, obo, op, args)
        out = ops_model.evaluate(self.ops, self.auth, subj, None if skip else obo, op, args, snap, self.clock.now(),
                                 approved=skip or self.approved.get(akey, 0) > 0)
        if out.used_approval and out.kind == ops_model.COMMIT and not skip:
            self.approved[akey] -= 1
        if out.kind != ops_model.COMMIT:
            return CallResult({"DENIED_AUTHORITY": "DENIED", "DENIED_RULE": "DENIED", "INVALID": "INVALID",
                               "NEEDS_APPROVAL": "INVALID", "UNKNOWN_OP": "UNKNOWN"}[out.kind], {"why": out.detail})
        if self._m("mutable_gated_input"):  # commit from the caller's live object, not the authorized copy
            args = {k: held[k] for k in list(held.keys())}
            out = ops_model.evaluate(self.ops, self.auth, self.admin, None, op, args, snap, self.clock.now())
        self._apply(out.effects)
        res = CallResult("OK", {"op": op, "args": args})
        if rid is not None:
            self.done[rid] = res
        return res

    def world_snapshot(self):
        from r3_shared.world import WorldReader
        return WorldReader(self.world._con.execute("PRAGMA database_list").fetchone()[2]).snapshot()

    def _apply(self, effects):
        w, ext = self.world, []
        with w.transaction():
            for e in effects:
                k = e["kind"]
                t, key = (e["ref"].split(":", 1) + [""])[:2] if k in ("create", "update", "delete") else ("", "")
                try:
                    if k == "create":
                        w.create(t, key, e["props"])
                    elif k == "update":
                        w.update(t, key, {f: nv for f, (_, nv) in e["changes"].items() if nv is not None})
                    elif k == "link":
                        w.link(*e["ref"].split("|"))
                    elif k == "external":
                        ext.append(e)
                except WorldConflict:
                    pass
        for e in ext:  # adapter writes use their own handle, outside the canonical transaction
            h = self.f(e["adapter"])
            h.external_write(e["adapter"], e["target"], e["payload"])
            h.close()

    def approve(self, token, operation, args, requester, on_behalf_of=None):
        sub = self._sub(token)
        if sub is None or self.mode == "deny-all" or not isinstance(args, dict):
            return CallResult("DENIED", {"reason": "no"})
        if self.mode != "allow-all":
            ok, why = oracle_approvals.validate(self.ops, self.auth, sub, requester, operation, args)
            if not ok:
                return CallResult("DENIED", {"reason": why})
        k = oracle_approvals.key(requester, on_behalf_of, operation, args)
        self.approved[k] = self.approved.get(k, 0) + 1
        return CallResult("OK", {})

    def read(self, token, operation, args):
        return CallResult("UNKNOWN", {})

    def crash(self):
        raise NotImplementedError

    def restart(self):
        raise NotImplementedError


class FakeVariant:
    audience = "fake"

    def __init__(self, mode, mutants=()):
        self.mode, self.name = mode, f"fake-{mode}"
        self.mutants = mutants_mod.validate(mutants)

    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock):
        return FakeDep(self.mode, domain, factory, verifier, ops_spec, auth_spec, clock, self.mutants)


MODES = ("correct", "allow-all", "direct-open", "deny-all")
VARIANTS = {f"fake-{m}": FakeVariant(m) for m in MODES}


def load(name, mutants=()):
    return FakeVariant(name.split("fake-", 1)[1], mutants)
