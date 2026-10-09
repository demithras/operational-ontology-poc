"""ExternalWorld client + process management (PROT-H28 1.1; P1f-2). The client is what an honest adapter uses on the DATA plane;
the CONTROL plane (issue_root, advance, observer_key, seed, close) needs the control socket path, which only the harness holds."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .extadapter import canon_json, validate_receipt
from .extcap import CapError  # noqa: F401  (re-export for callers)


class ExternalError(Exception):
    """ExternalWorld refused a control/protocol request, is unreachable, or the launcher guard refused."""


@dataclass(frozen=True)
class WriteReceipt:
    status: str   # "applied" | "refused" - returned to the ADAPTER only
    reason: str
    seq: int


def _call(path: str, req: dict, timeout: float = 15.0) -> dict:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall(canon_json(req).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        resp = json.loads(buf)
    except (OSError, ValueError) as exc:
        raise ExternalError(f"external world unreachable: {exc}") from exc
    if not resp.get("ok"):
        raise ExternalError(resp.get("error", "external world error"))
    return resp


class ExternalClient:
    def __init__(self, sock: str, ctl: str | None = None, timeout: float = 15.0):
        self._sock, self._ctl, self._timeout = str(sock), (str(ctl) if ctl else None), timeout

    def _control(self, req: dict) -> dict:
        if self._ctl is None:
            raise ExternalError("control plane not available to this client")
        return _call(self._ctl, req, self._timeout)

    def ping(self) -> dict:
        return _call(self._sock, {"op": "ping"}, self._timeout)

    def write(self, cap: str, operation: str, target: str, payload: dict, adapter_id: str) -> WriteReceipt:
        r = _call(self._sock, {"op": "write", "cap": cap, "operation": operation, "target": target, "payload": payload,
                               "adapter_id": adapter_id}, self._timeout)["receipt"]
        validate_receipt(r)
        return WriteReceipt(r["status"], r["reason"], r["seq"])

    # ---- control plane (harness only) -----------------------------------------------------------------------------
    def issue_root(self, deployment_id: str, system: str) -> str:
        return self._control({"op": "issue_root", "deployment": deployment_id, "system": system})["cap"]

    def advance(self, tick: int) -> None:
        self._control({"op": "advance", "tick": tick})

    def observer_key(self, deployment_id: str) -> str:
        return self._control({"op": "observer_key", "deployment": deployment_id})["key"]

    def seed(self, system: str, key: str, props: dict) -> None:
        self._control({"op": "seed", "system": system, "key": key, "props": props})

    def tick(self) -> int:
        return self._control({"op": "tick"})["tick"]

    def close(self) -> dict:
        r = self._control({"op": "close"})
        return {"root_key_hex": r["root_key_hex"], "head": r["head"]}

    def data_only(self) -> "ExternalClient":
        """The view handed to adapters: same data socket, no control path."""
        return ExternalClient(self._sock, None, self._timeout)


class ExternalProcess:
    def __init__(self, proc: subprocess.Popen, ext_dir: str, sock: str):
        self.proc, self.pid, self.ext_dir, self.sock_path, self.ctl_path = proc, proc.pid, str(ext_dir), str(sock), str(sock) + ".ctl"

    def client(self) -> ExternalClient:
        return ExternalClient(self.sock_path, self.ctl_path)

    def close(self) -> dict:
        try:
            return self.client().close()
        finally:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def start_external(ext_dir, systems_path, sock_path) -> ExternalProcess:
    """Harness/runner only: start ExternalWorld as a separate OS process. Refuses a dir that already holds a ledger."""
    Path(ext_dir).mkdir(parents=True, exist_ok=True)
    if (Path(ext_dir) / "external.db").exists():
        raise ExternalError("external dir already holds a ledger")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = subprocess.Popen([sys.executable, "-m", "r3_shared.extworld_server", "--dir", str(ext_dir), "--systems",
                             str(systems_path), "--socket", str(sock_path)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    line = proc.stdout.readline()
    if not line.startswith(b"READY"):
        proc.kill()
        raise ExternalError(f"external world failed to start: {proc.stderr.read().decode(errors='replace')[:500]}")
    return ExternalProcess(proc, ext_dir, sock_path)


def is_dev_id(exp_id: str) -> bool:
    return "-dev" in exp_id


def require_external(exp_id: str, env=None) -> tuple[str, str, str]:
    """G3-E31b pattern for the H28 runner: a non-dev experiment id REFUSES to run unless the launcher started ExternalWorld
    (R3_EXT_SOCK, R3_EXT_CTL, R3_EXT_DIR set and the data socket answers). Returns (sock, ctl, dir). Dev ids that find nothing
    set get ExternalError too - the caller may then start its own (start_external) as the dev path does for the anchor."""
    env = os.environ if env is None else env
    sock, ctl, d = env.get("R3_EXT_SOCK"), env.get("R3_EXT_CTL"), env.get("R3_EXT_DIR")
    if not (sock and ctl and d):
        raise ExternalError(f"refusing: experiment id {exp_id!r} requires R3_EXT_SOCK/R3_EXT_CTL/R3_EXT_DIR "
                            "(launch through the H28 launcher so ExternalWorld runs outside the sandbox)"
                            if not is_dev_id(exp_id) else "no ExternalWorld configured (dev id: start one with start_external)")
    try:
        ExternalClient(sock).ping()
    except ExternalError as exc:
        raise ExternalError(f"refusing: ExternalWorld at {sock} is not running: {exc}") from exc
    return sock, ctl, d
