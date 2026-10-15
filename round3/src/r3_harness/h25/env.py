"""One H25 deployment under test: world store (world_log, logical clock, writer allowlist), identity provider, the
variant's Deployment, and the harness-side SCHEDULE of calls (invoke/return from a harness counter, never the wall
clock). Every call is a plain dict (r3_oracle.const_judge.CALL_FIELDS); the oracle judges the schedule against the
world_log afterwards. CallResult is only copied into labels."""
from __future__ import annotations

import copy
import os
import shutil
import tempfile
import threading
import time

from r3_oracle.const_judge import CALL_FIELDS, judge
from r3_oracle.constitution import Constitution
from r3_shared.clock import LogicalClock
from r3_shared.identity import IdentityProvider
from r3_shared.variant import g3_call
from r3_shared.world import WorldStore

TTL = 10 ** 9
BAD_TOKEN = "invalid.token.value"


class G3Env:
    def __init__(self, variant, domain: str, ops: dict, auth_v3: dict, gov: dict, tag: str = "h25", mutants_note=None):
        self.variant, self.domain, self.ops, self.auth = variant, domain, ops, copy.deepcopy(auth_v3)
        self.gov = copy.deepcopy(gov)
        self.dir = tempfile.mkdtemp(prefix="h25-")
        self.clock = LogicalClock(0)
        self.store = WorldStore(os.path.join(self.dir, "world.db"), clock=self.clock)
        h = self.store.handle("harness-seed")
        with h.transaction():
            for o in ops["seed"]["objects"]:
                h.create(o["type"], o["key"], o["props"])
            for lk in ops["seed"]["links"]:
                h.link(lk["link_type"], lk["src"], lk["dst"])
        h.close()
        self.writers = frozenset(w for a in auth_v3["service_accounts"] for w in a["world_writers"])
        self.store.writers = self.writers
        self.idp = IdentityProvider(f"h25-secret-{tag}")
        self.reader = self.store.reader()
        self.snap0 = self.reader.snapshot()
        self.start_seq = self.snap0["log_head"]
        self.state_dir = os.path.join(self.dir, "state")
        os.makedirs(self.state_dir)
        self.dep = variant.deploy(domain, self.store.handle_factory(), self.idp.verifier(), ops, self.auth, self.clock,
                                  state_dir=self.state_dir, governance=copy.deepcopy(gov))
        aud = getattr(type(variant), "audience", None)
        if not isinstance(aud, str) or not aud:
            raise RuntimeError(f"variant {type(variant).__name__} defines no class attribute `audience`")
        self.aud, self._tokens = aud, {}
        self.C0 = Constitution.from_docs(self.auth, self.gov, ops)
        self.calls: list[dict] = []
        self._ctr, self._lock = 0, threading.Lock()

    # -- helpers ---------------------------------------------------------------------------------------
    def token(self, sub: str) -> str:
        if sub not in self._tokens:
            self._tokens[sub] = self.idp.issue(sub, self.aud, TTL, self.clock)
        return self._tokens[sub]

    def snapshot(self) -> dict:
        return self.reader.snapshot()

    def _tick(self) -> int:
        with self._lock:
            self._ctr += 1
            return self._ctr

    def _record(self, kind: str, fn, **fields) -> dict:
        rec = {k: None for k in CALL_FIELDS}
        rec.update({"kind": kind, "token_ok": True, "replay": False, "unsupported": False, "timeout": False,
                    "approved": False, "status": "EXC", "reason": None, "raised": False}, **fields)
        rec["tick_inv"], rec["inv"] = self.clock.now(), self._tick()
        t0 = time.perf_counter()
        try:
            res = fn()
            if res is not None:
                rec["status"], rec["reason"], rec["body"] = res.status, res.body.get("reason"), dict(res.body)
            else:
                rec["status"] = "OK"
        except NotImplementedError as exc:
            rec["unsupported"], rec["reason"] = True, str(exc)
        except Exception as exc:  # noqa: BLE001 - an exception from a variant is data
            rec["raised"], rec["reason"] = True, f"{type(exc).__name__}: {exc}"
            rec["status"] = "RAISED"
            if type(exc).__name__ == "WorldLockTimeout":
                rec["timeout"] = True
        rec["lat_ms"] = (time.perf_counter() - t0) * 1000.0
        rec["ret"], rec["tick_ret"] = self._tick(), self.clock.now()
        with self._lock:
            rec["n"] = len(self.calls)
            self.calls.append(rec)
        return rec

    # -- the calls -------------------------------------------------------------------------------------
    def act(self, actor: str, action: dict, rid: str, *, bad_token=False, crash=None, replay=False):
        tok = BAD_TOKEN if bad_token else self.token(actor)
        return self._record("constitutional", lambda: g3_call(self.dep, "constitutional", tok, copy.deepcopy(action), rid),
                            rid=rid, actor=actor, action=copy.deepcopy(action), token_ok=not bad_token, crash=crash,
                            replay=replay)

    def request(self, actor, op, args, rid, *, via="direct", obo=None, approved=False, bad_token=False):
        fn = self.dep.direct if via == "direct" else self.dep.call_tool
        tok = BAD_TOKEN if bad_token else self.token(actor)
        return self._record("request", lambda: fn(tok, op, copy.deepcopy(args), obo, rid), rid=rid, actor=actor, op=op,
                            args=copy.deepcopy(args), obo=obo, approved=approved, token_ok=not bad_token)

    def set_governance(self, doc: dict):
        def go():
            g3_call(self.dep, "set_governance", copy.deepcopy(doc))
        rec = self._record("set_governance", go, doc=copy.deepcopy(doc), rid=None)
        if rec["status"] == "OK":
            self.gov = copy.deepcopy(doc)
        return rec

    def set_authority(self, spec: dict):
        def go():
            self.dep.set_authority(copy.deepcopy(spec))
        rec = self._record("set_authority", go, spec=copy.deepcopy(spec), rid=None)
        if rec["status"] == "OK":
            self.auth = copy.deepcopy(spec)
        return rec

    def advance(self, n: int):
        rec = {k: None for k in CALL_FIELDS}
        rec.update({"kind": "advance", "inv": self._tick(), "status": "OK"})
        rec["to"] = self.clock.advance(n)
        rec["ret"] = self._tick()
        with self._lock:
            rec["n"] = len(self.calls)
            self.calls.append(rec)
        return rec

    def arm(self, point):
        self.dep.arm_crash(point)

    def crash_restart(self):
        self.dep.crash()
        self.dep.restart()

    def judge(self) -> dict:
        calls = [{k: c.get(k) for k in CALL_FIELDS} for c in self.calls]
        return judge(calls, self.reader.log(self.start_seq), self.C0, self.snap0, self.reader.snapshot(), self.writers)

    def close(self) -> None:
        try:
            self.reader.close()
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)
