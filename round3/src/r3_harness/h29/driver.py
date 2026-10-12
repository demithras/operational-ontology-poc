"""Executes ONE generated sequence against ONE variant through the host process and records RAW observations (no judgement here:
the closed ledgers and keys are only readable after the services close, so classification happens in judge.py). The harness plays exactly
the generated steps; every state change of the services goes through their control sockets; the variant is only ever touched through
DeploymentProxy (spawned host, hard SIGKILL crashes, resume=True in a NEW process). Ticks in the record are RELATIVE to the sequence base."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path

from r3_shared.clock import LogicalClock
from r3_shared.faultplane import CanonicalStateLost, DependencyUnavailable
from r3_shared.host import DeploymentProxy, HostDead, HostRemoteError
from r3_shared.identity import IdentityProvider
from r3_shared.world import WorldReader, WorldStore

from . import faults, rules, services, specs

TTL = 10 ** 6
ROUND3 = Path(__file__).resolve().parents[3]
FACTORY = "r3_harness.h29.adapters_h29:build"


def _norm(x):
    """Ledger row seqs (outcome `evidence`) are local to the service instance: the record keeps only whether any exist (the union of two seq spaces can collide, so even the count is layout dependent) so the evidence bytes do not
    depend on how many workers / service sets a run used (serial-vs-parallel byte identity)."""
    if isinstance(x, dict):
        return {k: (([0] if v else []) if k == "evidence" and isinstance(v, list) else _norm(v)) for k, v in x.items()}
    if isinstance(x, list):
        return [_norm(v) for v in x]
    return x


def _res(r) -> dict:
    return {"status": r.status, "body": _norm(r.body)}


class Run:
    def __init__(self, svc, variant: str, mutants, seq: dict, exp_id: str, base: int, workroot: str, extra_paths=(), host_timeout=120.0):
        self.svc, self.variant, self.mutants, self.seq, self.base = svc, variant, tuple(mutants), seq, base
        self.dep = f"{exp_id}:{variant.split(':')[-1]}:{seq['id']}"
        self.t = 0                                          # RELATIVE tick (the shared logical clock = base + t)
        self.work = Path(tempfile.mkdtemp(prefix="h29-", dir=workroot))
        self.world_path, self.hist_path = str(self.work / "world.db"), str(self.work / "hist.db")
        self.aud, self.layout = services.audience_of(variant), services.layout_of(variant)
        self.ops, self.auth0, self.systems = specs.load(seq["domain"])
        self.graph = specs.graph()
        self.secret = f"h29-{self.dep}"[:60] + "-secret"
        self.idp, self.tokens = IdentityProvider(self.secret), {}
        self.clock = LogicalClock(base)
        self.host: DeploymentProxy | None = None
        self.extra, self.timeout = tuple(extra_paths), host_timeout
        self.reqspec, self.faults, self.open_recoveries, self.kills = {}, {}, [], []
        self.ev: list = []
        self.rec = {"seq": seq["id"], "stratum": seq["stratum"], "domain": seq["domain"], "variant": variant, "dep": self.dep,
                    "base": base, "events": self.ev, "harness": [], "unsupported": 0, "deploy_error": None, "incarnations": []}
        self.obs_windows, self.stream = [], None
        self.workdir_hosts = self.work / "hosts"
        self.workdir_hosts.mkdir()

    # ---- helpers -----------------------------------------------------------------------------------------------
    def rel(self, a: int) -> int:
        return a - self.base

    def event(self, kind: str, **kw) -> dict:
        e = {"k": kind, "n": len(self.ev), "t": self.t, **kw}
        self.ev.append(e)
        return e

    def token(self, sub: str) -> str:
        if sub not in self.tokens:
            self.tokens[sub] = self.idp.issue(sub, self.aud, TTL, self.clock)
        return self.tokens[sub]

    def harness_row(self, name: str, **kw) -> None:
        self.rec["harness"].append({"row": name, "t": self.t, **kw})

    def call(self, name: str, *a, **k):
        """-> (CallResult|other|None, err). HostDead -> 'no_reply' and the host is marked dead (a kill is data, not an error)."""
        if self.host is None or not self.host.alive:
            return None, "no_host"
        try:
            return getattr(self.host, name)(*a, **k), None
        except HostDead:
            self._died()
            return None, "no_reply"
        except NotImplementedError as exc:
            self.rec["unsupported"] += 1
            return None, f"unsupported: {exc}"
        except TimeoutError as exc:
            self.harness_row("call_timeout", call=name)
            return None, f"timeout: {exc}"
        except DependencyUnavailable as exc:
            return None, f"DependencyUnavailable:{exc}"
        except Exception as exc:  # noqa: BLE001 - a variant exception is data
            return None, f"{type(exc).__name__}: {exc}"

    def _died(self) -> None:
        if not self.kills or self.kills[-1].get("resume") is not None:
            self.kills.append({"kill": self.t, "resume": None})
            self.event("host_dead", kill=self.t)

    # ---- setup -------------------------------------------------------------------------------------------------
    def setup(self) -> bool:
        ops = self.ops
        store = WorldStore(self.world_path, clock=self.clock)
        h = store.handle("harness-seed")
        with h.transaction(tag="seed"):
            for o in ops["seed"]["objects"]:
                h.create(o["type"], o["key"], o["props"])
            for lk in ops["seed"]["links"]:
                h.link(lk["link_type"], lk["src"], lk["dst"])
        h.close()
        h = store.handle("harness-refresh")
        with h.transaction(tag="refresh"):
            for o in ops["seed"]["objects"]:
                if o["type"] == "EvidenceSnapshot":
                    h.update(o["type"], o["key"], {"snapshotObservedAt": self.base})
        h.close()
        (self.work / "ops.json").write_text(json.dumps(ops))
        self.svc.advance_all(self.base)
        info = self.svc.auth.publish_info(self.auth0)           # G5-E2: version 0 at tick 0, before the first request
        self.event("publish", version=0, digest=info["digest"], effective=self.rel(info["effective_tick"]))
        return self.start_host(False)

    def deploy_spec(self, resume: bool, dep: str, paths: dict, obs_d: Path) -> dict:
        roots = {s: self.svc.ext.issue_root(dep, s) for s in self.systems["systems"]}
        lag = self.seq.get("obs_lag") or 0
        return {"domain": self.seq["domain"], "ops_spec_path": str(self.work / "ops.json"), "auth_spec": self.auth0,
                "world_path": paths["world"], "secret": self.secret, "clock_start": self.base + self.t, "state_dir": None,
                "history_path": paths["hist"], "anchor_sock": self.svc.anchor_sock, "governance": None, "resume": resume,
                "deployment_id": dep, "authority": {"sock": self.svc.auth_sock, "lease": faults.LEASE, "graph_path": str(specs.GRAPH_PATH)},
                "external": {"systems": self.systems, "data_sock": self.svc.ext_sock, "root_caps": roots,
                             "observer": {"ext_dir": str(obs_d), "key": self.svc.ext.observer_key(dep),
                                          "fault": {"kind": "lagging", "k": lag} if lag else None},
                             "window": self.systems["window"], "adapter_factory": FACTORY,
                             "adapter_args": {"domain": self.seq["domain"], "byz": ({**self.seq["byz"], "system": self.byz_system()}
                                                                                    if self.seq.get("byz") else None), "seed": self.seq["seed"]}}}

    def byz_system(self) -> str:
        if "_byz_system" not in self.__dict__:
            s = [n for n in sorted(self.systems["systems"]) if n != "GEN-NULL"]
            self._byz_system = s[self.seq["idx"] % len(s)]
        return self._byz_system

    def start_host(self, resume: bool, dep=None, paths=None, obs_tag="a") -> DeploymentProxy | None:
        dep = dep or self.dep
        paths = paths or {"world": self.world_path, "hist": self.hist_path}
        obs_d = services.obs_dir(self.work, obs_tag, self.svc.ext_dir)
        try:
            spec = self.deploy_spec(resume, dep, paths, obs_d)
            wd = self.workdir_hosts / obs_tag
            wd.mkdir(exist_ok=True)
            px = DeploymentProxy.start(self.variant, self.mutants, spec, str(wd), extra_paths=self.extra, timeout=self.timeout)
        except NotImplementedError as exc:
            self.rec["unsupported"] += 1
            self.rec["deploy_error"] = f"unsupported: {exc}"
            return None
        except CanonicalStateLost as exc:
            self.event("canonical_state_lost", msg=str(exc))
            return None
        except HostRemoteError as exc:
            self.rec["deploy_error"] = f"{exc.type_name}: {exc.message}"[:300]
            self.harness_row("host_spawn_failure", detail=str(exc)[:200])
            return None
        except Exception as exc:  # noqa: BLE001
            self.rec["deploy_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
            self.harness_row("host_spawn_failure", detail=str(exc)[:200])
            return None
        if obs_tag == "a":
            self.host = px
            self.rec["incarnations"].append({"n": len(self.rec["incarnations"]), "resume": resume, "t": self.t})
        return px

    # ---- clock -------------------------------------------------------------------------------------------------
    def obs_apply(self) -> None:
        up = not any(w["from"] <= self.t < w["to"] for w in self.obs_windows)
        services.obs_set(self.work / "obs-a", self.svc.ext_dir, up)

    def tick_to(self, target: int) -> None:
        while self.t < target:
            self.t += 1
            a = self.base + self.t
            self.clock.advance(1)
            self.svc.advance_all(a)
            if self.host is not None and self.host.alive:
                try:
                    self.host.advance(a)
                except HostDead:
                    self._died()
            self.obs_apply()

    # ---- run -----------------------------------------------------------------------------------------------------
    def run(self) -> dict:
        try:
            if not self.setup():
                self.finish()
                return self.rec
            for st in self.seq["steps"]:
                rules.validate_step(st)
                getattr(self, "s_" + st["op"])(st)
            from . import rc
            if self.open_recoveries:
                rc.rc2(self)
            if self.seq.get("boundary") == "B2":
                self.b2_replay_probe()
            self.finish()
        except Exception as exc:  # noqa: BLE001 - a harness bug is a visible row, never a silent pass
            self.harness_row("harness_exception", detail=f"{type(exc).__name__}: {exc}"[:300])
            try:
                self.finish()
            except Exception:  # noqa: BLE001
                pass
        finally:
            self.cleanup()
        return self.rec

    def anchor_head_after_ok(self, r):
        """G5-E20: transcript ordering. Immediately after an OK reply the harness reads the anchor head: the anchor entry of that decision must
        have a sequence <= this head (it was appended before the reply returned). None = no OK reply / stream unknown; -1 = head unreadable."""
        if r is None or getattr(r, "status", None) != "OK":
            return None
        from . import rc
        self.stream = self.stream or services.stream_of(self.hist_path)
        return rc._head(self, self.stream) if self.stream else None

    def b2_replay_probe(self) -> None:
        """PROT-H29 s9 B2 (G5-E24): the anchor is still unreachable; replay of any request this sequence sent must not be VERIFIED."""
        for rid in list(self.reqspec)[:12]:
            r, err = self.call("replay", rid)
            self.event("replay_probe", rid=rid, status=getattr(r, "status", None), reason=getattr(r, "reason", None), err=err)

    def cleanup(self) -> None:
        if self.host is not None:
            try:
                self.host.close() if self.host.alive else self.host.kill()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(self.work, ignore_errors=True)

    # ---- steps ---------------------------------------------------------------------------------------------------
    def s_advance(self, st):
        self.tick_to(self.t + st["n"])

    def s_request(self, st):
        self.reqspec.setdefault(st["rid"], st)
        self.send(st, "request")

    def send(self, st, kind, copy=0):
        tok = self.token(st["principal"])
        fn = "call_tool" if st["surface"] == "call_tool" else "direct"
        t0 = self.t
        r, err = self.call(fn, tok, st["operation"], dict(st["args"]), st["obo"], st["rid"])
        head = self.anchor_head_after_ok(r)
        return self.event(kind, i=st.get("i"), rid=st["rid"], principal=st["principal"], operation=st["operation"], surface=st["surface"],
                          tag=st.get("tag"), copy=copy, attacker=bool(st.get("attacker")), invalid_probe=bool(st.get("invalid_probe")), probe_shape=st.get("probe_shape"),
                          t=t0, args=st["args"], res=_res(r) if r is not None else None, err=err, inc=len(self.rec["incarnations"]) - 1,
                          anchor_head_at_reply=head)

    def s_approve(self, st):
        r, err = self.call("approve", self.token(st["approver"]), st["operation"], dict(st["args"]), st["requester"], st["obo"])
        self.event("approve", approver=st["approver"], requester=st["requester"], operation=st["operation"], args=st["args"],
                   res=_res(r) if r is not None else None, err=err)

    def s_delegate(self, st):
        r, err = self.call("delegate", self.token(st["principal"]), st["edge"], st["rid"])
        self.event("delegate", rid=st["rid"], principal=st["principal"], res=_res(r) if r is not None else None, err=err)

    def s_revoke(self, st):
        r, err = self.call("revoke", self.token(st["principal"]), st["edge_id"], st["rid"])
        self.event("revoke", rid=st["rid"], principal=st["principal"], res=_res(r) if r is not None else None, err=err)

    def s_read(self, st):
        r, err = self.call("read", self.token(st["principal"]), st["operation"], dict(st["args"]))
        self.event("read", i=st.get("i"), principal=st["principal"], operation=st["operation"], args=st["args"], tag=st.get("tag"),
                   res=_res(r) if r is not None else None, err=err)

    def s_redeliver(self, st):
        spec = self.reqspec.get(st["rid"])
        if spec is None:
            self.harness_row("redeliver_unknown_rid", rid=st["rid"])
            return
        n = st["copies"]
        if st["concurrent"] and n > 1:
            out = [None] * n

            def one(j):
                tok = self.token(spec["principal"])
                fn = "call_tool" if spec["surface"] == "call_tool" else "direct"
                out[j] = self.call(fn, tok, spec["operation"], dict(spec["args"]), spec["obo"], spec["rid"])
            ths = [threading.Thread(target=one, args=(j,)) for j in range(n)]
            for th in ths:
                th.start()
            for th in ths:
                th.join()
            for j, (r, err) in enumerate(out):
                self.event("redeliver", rid=st["rid"], principal=spec["principal"], operation=spec["operation"], copy=j + 1,
                           concurrent=True, res=_res(r) if r is not None else None, err=err, args=spec["args"])
        else:
            for j in range(n):
                e = self.send({**spec, "tag": "redeliver"}, "redeliver", copy=j + 1)
                e["concurrent"] = False

    def s_publish_authority(self, st):
        info = self.svc.auth.publish_info(specs.family(self.seq["domain"])[st["version"]])
        self.event("publish", version=st["version"], digest=info["digest"], effective=self.rel(info["effective_tick"]))

    def s_dispatch(self, st):
        r, err = self.call("dispatch_pending")
        self.event("dispatch", res=_res(r) if r is not None else None, err=err)

    def s_reconcile(self, st):
        wm = self.base + st["watermark"]
        r, err = self.call("reconcile", st["rid"], wm)
        lag = self.seq.get("obs_lag") or 0
        down = any(w["from"] <= self.t < w["to"] for w in self.obs_windows)
        self.event("reconcile", rid=st["rid"], watermark=st["watermark"], res=_res(r) if r is not None else None, err=err,
                   fault={"kind": "unavailable"} if down else ({"kind": "lagging", "k": lag} if lag else None))

    def s_crash(self, st):
        if self.host is not None and self.host.alive:
            try:
                self.host.arm(st["point"], st["key"])
            except HostDead:
                self._died()
        self.event("crash_armed", point=st["point"], key=st["key"])

    def s_fault_start(self, st):
        from . import inject
        inject.start(self, st)

    def s_fault_heal(self, st):
        w = self.faults.get(st["fid"])
        if w is not None and self.t < w["to"]:
            self.tick_to(w["to"])
        self.event("fault_heal", fid=st["fid"])

    def s_tamper(self, st):
        from . import rc
        rc.do_tamper(self, st)

    def s_resume(self, st):
        from . import rc
        rc.resume(self)

    def s_recovery_schedule(self, st):
        from . import rc
        if self.open_recoveries:
            rc.rc2(self)

    # ---- end of sequence ---------------------------------------------------------------------------------------
    def finish(self) -> None:
        from . import collect
        collect.finish(self)
