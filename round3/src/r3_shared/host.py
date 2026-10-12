"""Variant host process (PROTOCOL-P1g P1g-6): `python -m r3_shared.host --variant <name|module:Class> --mutants <csv> --workdir <dir> --ctl <fd>`.
Each incarnation is a FRESH interpreter (subprocess exec of this module over a socketpair: no fork of the harness, no inherited
state, no import-time temp dirs). A crash is SIGKILL of this process at an armed crash point (faultplane); resume = a NEW host
with deploy_spec["resume"] = True over the same durable paths. The shared LogicalClock moves only through harness advance() RPCs.
Wire: one JSON object per line. Harness side: DeploymentProxy (same method names as Deployment + arm/advance/pid/kill/close).

deploy_spec keys: domain, ops_spec_path, auth_spec, world_path, secret, clock_start, state_dir|None, history_path|None, anchor_sock|None,
governance|None, resume, deployment_id, authority {sock, lease, graph_path}|None, external {systems, data_sock, root_caps,
observer {ext_dir, key, fault{kind,k,reads}|None}, window, adapter_factory "module:function", adapter_args}|None.
adapter_factory(ctx) -> {system: ActionAdapter}; ctx = {systems, data_sock, deployment_id, adapter_args, clock}."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path

from . import faultplane
from .faultplane import CanonicalStateLost, DependencyUnavailable

START_METHOD = "spawn"   # fresh interpreter per incarnation; asserted by tests
CP8_KEY = "dispatch_pending"   # key of CP8_during_recovery: the first dispatch_pending after resume
_REQ_IDX = {"call_tool": 4, "direct": 4, "delegate": 2, "revoke": 2, "constitutional": 2, "reconcile": 0}
_REQ_KW = "request_id"
_REMOTE = {"NotImplementedError": NotImplementedError, "ValueError": ValueError, "TypeError": TypeError, "KeyError": KeyError,
           "RuntimeError": RuntimeError, "CanonicalStateLost": CanonicalStateLost}


class HostDead(Exception):
    """The host process is gone (killed at a crash point or otherwise): the in-flight call's reply is `no_reply`."""


class HostRemoteError(Exception):
    def __init__(self, type_name: str, message: str):
        super().__init__(f"{type_name}: {message}")
        self.type_name, self.message = type_name, message


# ---- JSON codec -----------------------------------------------------------------------------------------------------
def _types():
    from .variant import CallResult, ReplayResult, ToolDescriptor
    return {"CallResult": CallResult, "ReplayResult": ReplayResult, "ToolDescriptor": ToolDescriptor}


def enc(x):
    T = _types()
    for name, cls in T.items():
        if isinstance(x, cls):
            return {"__t": name, **{k: enc(v) for k, v in x.__dict__.items()}}
    if isinstance(x, bytes):
        return {"__b": x.hex()}
    if isinstance(x, dict):
        return {k: enc(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set, frozenset)):
        return [enc(v) for v in (sorted(x) if isinstance(x, (set, frozenset)) else x)]
    return x


def dec(x):
    if isinstance(x, dict):
        if "__b" in x:
            return bytes.fromhex(x["__b"])
        if "__t" in x:
            return _types()[x["__t"]](**{k: dec(v) for k, v in x.items() if k != "__t"})
        return {k: dec(v) for k, v in x.items()}
    if isinstance(x, list):
        return [dec(v) for v in x]
    return x


# ---- host side ------------------------------------------------------------------------------------------------------
def _load_variant(name: str, mutants):
    if ":" in name:
        mod, cls = name.split(":")
        return getattr(importlib.import_module(mod), cls)(mutants)
    from .registry import load_variant
    return load_variant(name, mutants)


def _build(spec: dict, variant, clock):
    from .anchor import AnchorClient
    from .authsvc import AuthorityClient
    from .extobs import ObservationClient, ObserverFault
    from .histstore import HistoryStore
    from .identity import IdentityProvider
    from .variant import AuthorityBinding, ExternalBinding, g4_deploy, g5_deploy
    from .world import WorldStore
    resume = bool(spec.get("resume"))
    if resume:
        durable = [p for p in (spec.get("state_dir"), spec.get("history_path")) if p]
        if not os.path.exists(spec["world_path"]) or (durable and not any(os.path.exists(p) for p in durable)):
            raise CanonicalStateLost("durable stores absent")  # PROT-H29 s9 B4: never start empty
    store = WorldStore(spec["world_path"], clock=clock)
    ops, auth = json.loads(Path(spec["ops_spec_path"]).read_text()), spec["auth_spec"]
    kw = {"state_dir": spec.get("state_dir"), "history": HistoryStore(spec["history_path"]) if spec.get("history_path") else None,
          "anchor": AnchorClient(spec["anchor_sock"]) if spec.get("anchor_sock") else None, "governance": spec.get("governance")}
    ext = spec.get("external")
    if ext:
        fn_mod, fn = ext["adapter_factory"].split(":")
        adapters = getattr(importlib.import_module(fn_mod), fn)(
            {"systems": ext["systems"], "data_sock": ext["data_sock"], "deployment_id": spec["deployment_id"],
             "adapter_args": ext.get("adapter_args", {}), "clock": clock})
        o = ext["observer"]
        fault = o.get("fault")
        obs = ObservationClient(o["ext_dir"], o["key"], ext["systems"],
                                ObserverFault(fault["kind"], fault.get("k", 0), frozenset(fault.get("reads", ()))) if fault else None)
        kw["external"] = ExternalBinding(ext["systems"], adapters, ext["root_caps"], obs, ext["window"])
    args = (spec["domain"], store.handle_factory(), IdentityProvider(spec["secret"]).verifier(), ops, auth, clock)
    a = spec.get("authority")
    if a is not None or resume:
        src = None if a is None else AuthorityBinding(AuthorityClient(a["sock"], spec["deployment_id"]), a["lease"],
                                                      json.loads(Path(a["graph_path"]).read_text()))
        return g5_deploy(variant, *args, authority_source=src, resume=resume, **kw)
    return g4_deploy(variant, *args, **kw) if ext else variant.deploy(*args, **kw)


def _invoke(dep, method: str, args, kwargs):
    from . import variant as V
    for gate in ("g2", "g3", "g4", "g5"):
        if method in getattr(V, f"{gate.upper()}_METHODS"):
            return getattr(V, f"{gate}_call")(dep, method, *args, **kwargs)
    return getattr(dep, method)(*args, **kwargs)


def serve(variant_name: str, mutants, ctl_fd: int) -> int:
    from .clock import LogicalClock
    from .variant import Deployment
    methods = {n for n in dir(Deployment) if not n.startswith("_")} | {"recovery_view", "dependency_status"}
    sock = socket.socket(fileno=ctl_fd)
    rf, wlock = sock.makefile("rb"), threading.Lock()
    st = {"dep": None, "clock": None, "last_key": "", "inflight": 0, "first_dispatch": False}
    cv = threading.Condition()

    def send(obj):
        with wlock:
            sock.sendall(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\n")

    def work(rid, method, args, kwargs):
        try:
            if method == "reconcile":
                faultplane.set_context_key(str(args[0] if args else kwargs.get("request_id", "")))   # CP7 key
            if method == "dispatch_pending" and st["first_dispatch"]:
                st["first_dispatch"] = False
                faultplane.crashpoint("CP8_during_recovery", CP8_KEY)
            res = _invoke(st["dep"], method, args, kwargs)
            send({"id": rid, "ok": True, "result": enc(res)})
        except BaseException as exc:  # noqa: BLE001 - a variant exception is data
            send({"id": rid, "ok": False, "error": {"type": type(exc).__name__, "msg": str(exc),
                                                      "dep": exc.node if isinstance(exc, DependencyUnavailable) else None}})
        finally:
            key = _key(method, args, kwargs)
            with cv:
                if key:
                    st["last_key"] = key
                st["inflight"] -= 1
                idle = st["inflight"] == 0
            if idle:
                faultplane.crashpoint("CP6_idle", st["last_key"])   # between two calls, after the reply went out

    def _key(method, args, kwargs):
        if method not in _REQ_IDX:
            return ""
        v = kwargs.get(_REQ_KW) if _REQ_KW in kwargs else (args[_REQ_IDX[method]] if len(args) > _REQ_IDX[method] else None)
        return v if isinstance(v, str) else ""

    for line in rf:
        r = json.loads(line)
        rid, m, args, kwargs = r["id"], r["method"], dec(r.get("args", [])), dec(r.get("kwargs", {}))
        try:
            if m == "__deploy__":
                st["clock"] = LogicalClock(args[0].get("clock_start", 0))
                st["dep"] = _build(args[0], _load_variant(variant_name, mutants), st["clock"])
                st["first_dispatch"] = bool(args[0].get("resume"))
                send({"id": rid, "ok": True, "result": {"pid": os.getpid()}})
            elif m == "__advance__":
                send({"id": rid, "ok": True, "result": st["clock"].advance(max(0, args[0] - st["clock"].now()))})
            elif m == "__arm__":
                faultplane.arm(args[0], args[1])
                send({"id": rid, "ok": True, "result": None})
            elif m == "__shutdown__":
                send({"id": rid, "ok": True, "result": None})
                return 0
            elif m in methods and st["dep"] is not None:
                with cv:
                    st["inflight"] += 1
                threading.Thread(target=work, args=(rid, m, args, kwargs), daemon=True).start()
            else:
                raise AttributeError(f"unknown method {m!r}" if st["dep"] is not None else "not deployed")
        except BaseException as exc:  # noqa: BLE001
            send({"id": rid, "ok": False, "error": {"type": type(exc).__name__, "msg": str(exc), "dep": None}})
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", required=True)
    ap.add_argument("--mutants", default="")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--ctl", type=int, required=True)
    a = ap.parse_args(argv)
    return serve(a.variant, [m for m in a.mutants.split(",") if m], a.ctl)


# ---- harness side -------------------------------------------------------------------------------------------------------
class DeploymentProxy:
    """Harness side. Methods of Deployment (+ G2..G5) are forwarded by name; a dead host raises HostDead."""

    def __init__(self, proc: subprocess.Popen, sock: socket.socket):
        self.proc, self.pid, self._sock = proc, proc.pid, sock
        self._wlock, self._pending, self._n, self._dead = threading.Lock(), {}, 0, False
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    @classmethod
    def start(cls, variant: str, mutants, deploy_spec: dict, workdir: str, extra_paths=(), timeout: float = 120.0) -> "DeploymentProxy":
        """Spawn a fresh host and deploy. `workdir` must be a caller-made directory (it is named on the command line so leak
        hygiene can attribute the process exactly); the host's output goes to <workdir>/host-<pid>.log."""
        a, b = socket.socketpair()
        src = str(Path(__file__).resolve().parents[1])
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([src, *map(str, extra_paths), os.environ.get("PYTHONPATH", "")])}
        log = open(Path(workdir) / f"host-{len(list(Path(workdir).glob('host-*.log')))}.log", "wb")
        proc = subprocess.Popen([sys.executable, "-m", "r3_shared.host", "--variant", variant, "--mutants", ",".join(sorted(mutants)),
                                 "--workdir", str(workdir), "--ctl", str(b.fileno())], pass_fds=(b.fileno(),), env=env,
                                stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        b.close()
        log.close()
        px = cls(proc, a)
        try:
            px._rpc("__deploy__", (deploy_spec,), {}, timeout)
        except BaseException:
            px.kill()
            raise
        return px

    def _read(self):
        try:
            for line in self._sock.makefile("rb"):
                r = json.loads(line)
                slot = self._pending.pop(r["id"], None)
                if slot is not None:
                    slot[1].update(r)
                    slot[0].set()
        except (OSError, ValueError):
            pass
        self._dead = True
        for slot in list(self._pending.values()):
            slot[0].set()
        try:
            self.proc.wait()   # reap: a killed host leaves no zombie
        except Exception:  # noqa: BLE001
            pass

    def _rpc(self, method, args, kwargs, timeout=120.0):
        if self._dead:
            raise HostDead("host is dead")
        with self._wlock:
            self._n += 1
            rid, slot = self._n, (threading.Event(), {})
            self._pending[rid] = slot
            try:
                self._sock.sendall(json.dumps({"id": rid, "method": method, "args": enc(list(args)), "kwargs": enc(kwargs)}).encode() + b"\n")
            except OSError as exc:
                self._pending.pop(rid, None)
                raise HostDead(str(exc)) from exc
        if not slot[0].wait(timeout):
            raise TimeoutError(f"host call {method} timed out")
        if not slot[1]:
            raise HostDead(f"host died during {method}")
        r = slot[1]
        if r["ok"]:
            return dec(r["result"])
        e = r["error"]
        if e.get("dep"):
            raise DependencyUnavailable(e["dep"])
        raise _REMOTE.get(e["type"], lambda m: HostRemoteError(e["type"], m))(e["msg"])

    def __getattr__(self, method):
        if method.startswith("_") or method in ("proc", "pid"):
            raise AttributeError(method)
        return lambda *a, **k: self._rpc(method, a, k)

    def arm(self, point: str, key: str) -> None:
        self._rpc("__arm__", (point, key), {})

    def advance(self, tick: int) -> int:
        return self._rpc("__advance__", (tick,), {})

    @property
    def alive(self) -> bool:
        return not self._dead and self.proc.poll() is None

    def wait_dead(self, timeout: float = 30.0) -> int:
        return self.proc.wait(timeout)

    def kill(self) -> None:
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.proc.wait()
        self._reader.join(5)

    def close(self) -> None:
        if self.alive:
            try:
                self._rpc("__shutdown__", (), {}, 20)
            except Exception:  # noqa: BLE001
                pass
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.kill()
        self._sock.close()


if __name__ == "__main__":
    sys.exit(main())
