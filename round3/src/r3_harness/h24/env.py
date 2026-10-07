"""One H24 deployment under test: world store (with world_log, clock, writer allowlist), identity provider, the variant's
Deployment, and the harness-side SCHEDULE of calls (invoke/return from a harness counter, not the wall clock).
Every call is recorded as a plain dict (r3_oracle.judge_v2.CALL_FIELDS); the oracle judges the schedule against the
world_log afterwards. CallResult is only copied into `status`/`reason`/`body` labels."""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
import threading

from r3_oracle import ops_model
from r3_oracle.authority_v2 import RefAuthority
from r3_oracle.judge_v2 import judge
from r3_shared.clock import LogicalClock
from r3_shared.identity import IdentityProvider
from r3_shared.variant import g2_call
from r3_shared.world import WorldStore

TTL = 10 ** 9


class G2Env:
    def __init__(self, variant, domain: str, ops: dict, auth_v2: dict, tag: str = "h24"):
        self.variant, self.domain, self.ops, self.auth = variant, domain, ops, copy.deepcopy(auth_v2)
        self.dir = tempfile.mkdtemp(prefix="h24-")
        self.clock = LogicalClock(0)
        self.store = WorldStore(os.path.join(self.dir, "world.db"), clock=self.clock)
        h = self.store.handle("harness-seed")
        with h.transaction():
            for o in ops["seed"]["objects"]:
                h.create(o["type"], o["key"], o["props"])
            for lk in ops["seed"]["links"]:
                h.link(lk["link_type"], lk["src"], lk["dst"])
        h.close()
        self.writers = frozenset(w for a in auth_v2["service_accounts"] for w in a["world_writers"])
        self.store.writers = self.writers  # allowlist applies to everything the variant opens from here on
        self.idp = IdentityProvider(f"h24-secret-{tag}")
        self.reader = self.store.reader()
        self.snap0 = self.reader.snapshot()
        self.start_seq = self.snap0["log_head"]
        self.state_dir = os.path.join(self.dir, "state")
        os.makedirs(self.state_dir)
        self.dep = variant.deploy(domain, self.store.handle_factory(), self.idp.verifier(), ops, self.auth, self.clock,
                                  state_dir=self.state_dir)
        aud = getattr(type(variant), "audience", None)
        if not isinstance(aud, str) or not aud:
            raise RuntimeError(f"variant {type(variant).__name__} defines no class attribute `audience`")
        self.aud, self._tokens = aud, {}
        self.ra0 = RefAuthority.from_spec(self.auth)
        self.mirror = self.ra0  # generator-side guess of the authority state (targeting only; never a verdict)
        self.calls: list[dict] = []
        self.committed: set = set()  # attribute read by r3_harness.h23.goodargs.pick_args
        self._ctr, self._lock = 0, threading.Lock()

    # -- helpers -----------------------------------------------------------------------------------
    def snapshot(self) -> dict:
        return self.reader.snapshot()

    def token(self, sub: str) -> str:
        if sub not in self._tokens:
            self._tokens[sub] = self.idp.issue(sub, self.aud, TTL, self.clock)
        return self._tokens[sub]

    def principals(self) -> list[dict]:
        return self.auth["principals"]

    def _tick(self) -> int:
        with self._lock:
            self._ctr += 1
            return self._ctr

    def _record(self, kind: str, fn, **fields) -> dict:
        """Run fn() (a variant call) and append the schedule row. NotImplementedError -> unsupported (never SUPPORTED)."""
        rec = {k: None for k in ("rid", "actor", "obo", "op", "args", "edge", "edge_id", "spec", "to", "body", "crash")}
        rec.update({"kind": kind, "approved": False, "replay": False, "unsupported": False, "timeout": False,
                    "status": "EXC", "reason": None}, **fields)
        rec["tick_inv"], rec["inv"] = self.clock.now(), self._tick()
        try:
            res = fn()
            if res is not None:
                rec["status"], rec["reason"], rec["body"] = res.status, res.body.get("reason"), dict(res.body)
            else:
                rec["status"] = "OK"
        except NotImplementedError as exc:
            rec["unsupported"], rec["reason"] = True, str(exc)
        except Exception as exc:  # noqa: BLE001 - an exception from a variant is data, not a harness crash
            rec["reason"] = f"{type(exc).__name__}: {exc}"
        rec["ret"], rec["tick_ret"] = self._tick(), self.clock.now()
        with self._lock:
            rec["n"] = len(self.calls)
            self.calls.append(rec)
        return rec

    # -- the calls ----------------------------------------------------------------------------------
    def request(self, actor, obo, op, args, rid, *, via="direct", approved=False, replay=False, crash=None):
        fn = self.dep.direct if via == "direct" else self.dep.call_tool
        return self._record("request", lambda: fn(self.token(actor), op, copy.deepcopy(args), obo, rid), rid=rid,
                            actor=actor, obo=obo, op=op, args=copy.deepcopy(args), approved=approved, replay=replay,
                            crash=crash)

    def delegate(self, edge, rid, *, actor=None, crash=None, intent=None):
        actor = actor or edge.get("issuer")
        rec = self._record("delegate", lambda: g2_call(self.dep, "delegate", self.token(actor), copy.deepcopy(edge), rid),
                           rid=rid, actor=actor, edge=copy.deepcopy(edge), crash=crash)
        rec["intent"] = intent
        return rec

    def revoke(self, actor, edge_id, rid, *, crash=None):
        return self._record("revoke", lambda: g2_call(self.dep, "revoke", self.token(actor), edge_id, rid), rid=rid,
                            actor=actor, edge_id=edge_id, crash=crash)

    def set_authority(self, spec: dict):
        def go():
            self.dep.set_authority(copy.deepcopy(spec))
        rec = self._record("set_authority", go, spec=copy.deepcopy(spec), rid=None)
        if rec["status"] == "OK":
            self.auth = copy.deepcopy(spec)
        return rec

    def approve(self, approver, requester, obo, op, args):
        return self.dep.approve(self.token(approver), op, copy.deepcopy(args), requester, obo)

    def advance(self, n: int):
        rec = {"kind": "advance", "to": None, "inv": self._tick(), "ret": None, "rid": None, "status": "OK"}
        rec["to"] = self.clock.advance(n)
        rec["ret"] = self._tick()
        with self._lock:
            rec["n"] = len(self.calls)
            self.calls.append(rec)
        return rec

    def authority_used(self, rid):
        return self._record("authority_used", lambda: g2_call(self.dep, "authority_used", rid), rid=rid)

    def arm(self, point):
        self.dep.arm_crash(point)

    def crash_restart(self):
        self.dep.crash()
        self.dep.restart()

    # -- judge ---------------------------------------------------------------------------------------
    def judge(self) -> dict:
        calls = [{k: c.get(k) for k in (*_FIELDS, "intent", "body")} for c in self.calls]
        return judge(calls, self.reader.log(self.start_seq), self.ra0, self.snap0, self.reader.snapshot(), self.ops,
                     self.writers)

    def close(self) -> None:
        try:
            self.reader.close()
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)


_FIELDS = ("n", "kind", "rid", "actor", "obo", "op", "args", "edge", "edge_id", "spec", "to", "approved", "status",
           "reason", "inv", "ret", "tick_inv", "tick_ret", "crash", "replay", "unsupported", "timeout")
_ = ops_model  # imported for subclass convenience
