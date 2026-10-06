"""Test-only H23 fakes (never registered). They reuse the oracle's rules, so a "correct" fake is correct BY
CONSTRUCTION and exists to prove the harness can say SUPPORTED; the broken fakes prove it says REJECTED/not SUPPORTED.

modes: correct | allow-all | direct-open (tools hide, direct skips authz) | deny-all
The fakes honour the four H23 mutants through their own frozen constructor set (`FakeVariant(mode, mutants)`) so the mutation proof can be tested.
"""
from __future__ import annotations

import copy
import json
import threading
import time
from pathlib import Path

from r3_oracle import approvals as oracle_approvals
from r3_oracle import authority, ops_model
from r3_shared import mutants as mutants_mod
from r3_shared.identity import TokenError
from r3_shared.variant import CallResult, ToolDescriptor
from r3_shared.world import WorldConflict


class FakeDep:
    audience = "fake"

    def __init__(self, mode, domain, factory, verifier, ops, auth, clock, mutants=frozenset(), state_dir=None):
        self.mutants = mutants
        self.state_dir, self.crashed, self._armed = state_dir, False, None
        self._lock = threading.RLock()
        self.mode, self.domain, self.f, self.verifier = mode, domain, factory, verifier
        self.ops, self.auth, self.clock = ops, auth, clock
        self.world, self.done, self.approved = factory("fake-service"), {}, {}
        self.admin = next(p["id"] for p in auth["principals"] if "admin" in p["roles"])

    # --- PROT-H23-A8: durable request ledger (state_dir) unless the volatile mutant is on -------------
    def _ledger_file(self):
        return Path(self.state_dir) / "ledger.json" if self.state_dir else None

    def _load_ledger(self):
        p = self._ledger_file()
        if self._m("ledger_after_commit_volatile") or p is None or not p.exists():
            return {}
        return json.loads(p.read_text())

    def _store_ledger(self, rid):
        p = self._ledger_file()
        if self._m("ledger_after_commit_volatile") or p is None:
            return
        led = self._load_ledger()
        led[rid] = True
        p.write_text(json.dumps(led))

    def _appr_file(self):
        return Path(self.state_dir) / "approvals.json" if self.state_dir else None

    def _persist_approvals(self):
        p = self._appr_file()
        if p is not None and not getattr(self, "approvals_volatile", False):
            p.write_text(json.dumps(self.approved))

    def _consume(self, akey):
        self.approved[akey] -= 1
        if not getattr(self, "approvals_volatile", False):
            self._persist_approvals()

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
        if self._m("unsynchronized_commit"):
            return self._run_locked(token, op, args, obo, rid, backstop)
        with self._lock:
            return self._run_locked(token, op, args, obo, rid, backstop)

    def _run_locked(self, token, op, args, obo, rid, backstop):
        if self.crashed:
            return CallResult("UNAVAILABLE", {"reason": "crashed"})
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
        if rid is not None and (rid in self.done or rid in self._load_ledger()):
            return self.done.get(rid, CallResult("OK", {"replayed": True}))
        subj = self.admin if skip else sub
        snap = self.world_snapshot()
        akey = oracle_approvals.key(sub, obo, op, args)
        out = ops_model.evaluate(self.ops, self.auth, subj, None if skip else obo, op, args, snap, self.clock.now(),
                                 approved=skip or self.approved.get(akey, 0) > 0)
        if self._m("unsynchronized_commit"):
            time.sleep(0.003)  # authorize->consume window the missing lock leaves open
        if out.kind != ops_model.COMMIT:
            return CallResult({"DENIED_AUTHORITY": "DENIED", "DENIED_RULE": "DENIED", "INVALID": "INVALID",
                               "NEEDS_APPROVAL": "INVALID", "UNKNOWN_OP": "UNKNOWN"}[out.kind], {"why": out.detail})
        if self._m("mutable_gated_input"):  # commit from the caller's live object, not the authorized copy
            args = {k: held[k] for k in list(held.keys())}
            out = ops_model.evaluate(self.ops, self.auth, self.admin, None, op, args, snap, self.clock.now())
        armed, self._armed = self._armed, None
        if armed == "before_commit":
            return self._die()
        if out.used_approval and not skip:  # R-6: consumed durably, at commit time (never by a crashed-before-commit call)
            self._consume(akey)
        if rid is not None and not self._m("ledger_after_commit_volatile"):
            self._store_ledger(rid)  # durable BEFORE the world write; a before_commit crash leaves it unrecorded
        self._apply(out.effects)
        if armed == "after_commit":
            return self._die()
        res = CallResult("OK", {"op": op, "args": args})
        if rid is not None:
            self.done[rid] = res
        return res

    def _die(self):
        self.crashed = True
        return CallResult("UNKNOWN", {"reason": "crashed"})

    def world_snapshot(self):
        from r3_shared.world import WorldReader
        r = WorldReader(self.world._con.execute("PRAGMA database_list").fetchone()[2])
        try:
            return r.snapshot()
        finally:
            r.close()

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
        with self._lock:
            if self.crashed:
                return CallResult("UNAVAILABLE", {"reason": "crashed"})
            return self._approve(token, operation, args, requester, on_behalf_of)

    def _approve(self, token, operation, args, requester, on_behalf_of):
        sub = self._sub(token)
        if sub is None or self.mode == "deny-all" or not isinstance(args, dict):
            return CallResult("DENIED", {"reason": "no"})
        if self.mode != "allow-all":
            ok, why = oracle_approvals.validate(self.ops, self.auth, sub, requester, operation, args)
            if not ok:
                return CallResult("DENIED", {"reason": why})
        k = oracle_approvals.key(requester, on_behalf_of, operation, args)
        self.approved[k] = self.approved.get(k, 0) + 1
        self._persist_approvals()
        return CallResult("OK", {})

    def read(self, token, operation, args):
        return CallResult("UNKNOWN", {})

    def arm_crash(self, point):
        if point not in ("before_commit", "after_commit"):
            raise ValueError(point)
        self._armed = point

    def crash(self):
        self.crashed, self._armed, self.done = True, None, {}  # memory is lost

    def restart(self):
        self.crashed, self._armed, self.done = False, None, {}
        p = self._appr_file()  # R-6: approvals are durable; the volatile fake (test negative) loses them
        self.approved = json.loads(p.read_text()) if p is not None and p.exists() and not getattr(self, "approvals_volatile", False) else {}



class FakeVariant:
    audience = "fake"

    def __init__(self, mode, mutants=()):
        self.mode, self.name = mode, f"fake-{mode}"
        self.mutants = mutants_mod.validate(mutants)

    def deploy(self, domain, factory, verifier, ops_spec, auth_spec, clock, state_dir=None):
        return FakeDep(self.mode, domain, factory, verifier, ops_spec, auth_spec, clock, self.mutants, state_dir)


MODES = ("correct", "allow-all", "direct-open", "deny-all")
VARIANTS = {f"fake-{m}": FakeVariant(m) for m in MODES}


def load(name, mutants=()):
    return FakeVariant(name.split("fake-", 1)[1], mutants)
