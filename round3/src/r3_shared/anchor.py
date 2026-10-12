"""Anchor client (the only anchor module variants may import) + harness-side start/verify. PROT-H27 s2, s4; P1d-6.
Wire protocol: one JSON object per line over a Unix socket; one request per connection."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

from . import faultplane
from .faultplane import DependencyUnavailable

ZERO = "0" * 64
LOG_NAME, KEY_NAME, HEAD_NAME = "anchor.log", "KEY.revealed", "HEAD.final"


class AnchorError(Exception):
    """Anchor refused or is unreachable (seq gap/duplicate, closed, socket failure)."""


class AnchorUnavailable(AnchorError, DependencyUnavailable):
    """G5: the anchor is inside a server-side drop window, or dropped the reply (reply_lost). An append may
    or may not have been applied: the caller must treat the commit as in doubt. str(e) == "ANCHOR"."""

    def __init__(self, detail: str = ""):
        DependencyUnavailable.__init__(self, "ANCHOR")
        self.detail = detail


def canon(x) -> bytes:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def entry_mac(key: bytes, entry: dict) -> str:
    return hmac.new(key, canon({k: v for k, v in entry.items() if k != "mac"}), hashlib.sha256).hexdigest()


def line_sha(line: bytes) -> str:
    return hashlib.sha256(line).hexdigest()


class AnchorClient:
    def __init__(self, sock_path: str, timeout: float = 10.0):
        self._sock, self._timeout = str(sock_path), timeout

    def _call(self, req: dict) -> dict:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self._timeout)
                s.connect(self._sock)
                s.sendall(canon(req) + b"\n")
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
            if buf == b"":  # connection closed without a reply: reply_lost window (G5) -> commit status in doubt
                raise AnchorUnavailable("connection closed without a reply")
            resp = json.loads(buf)
        except (OSError, ValueError) as exc:
            raise AnchorError(f"anchor unreachable: {exc}") from exc
        if not resp.get("ok"):
            if resp.get("unavailable"):
                raise AnchorUnavailable("anchor partitioned")
            raise AnchorError(resp.get("error", "anchor error"))
        return resp

    def append(self, stream: str, seq: int, decision_id: str, root: str) -> dict:
        """Receipt = the committed log entry (with mac). AnchorError on seq != head+1 (gap) or a second append."""
        entry = self._call({"op": "append", "stream": stream, "seq": seq, "decision_id": decision_id, "root": root})["entry"]
        faultplane.crashpoint("CP3_after_anchor_append", decision_id)  # G5: no-op unless a host armed it
        return entry

    def get(self, stream: str, seq: int) -> dict | None:
        return self._call({"op": "get", "stream": stream, "seq": seq})["entry"]

    def lookup(self, stream: str, decision_id: str) -> dict | None:
        return self._call({"op": "lookup", "stream": stream, "decision_id": decision_id})["entry"]

    def head(self, stream: str) -> dict | None:
        return self._call({"op": "head", "stream": stream})["entry"]


class AnchorControl:
    """Harness only (G5): the anchor's control plane on <sock>.ctl."""

    def __init__(self, ctl_path: str, timeout: float = 10.0):
        self._c = AnchorClient(ctl_path, timeout)

    def advance(self, tick: int) -> int:
        return self._c._call({"op": "advance", "tick": tick})["tick"]

    def tick(self) -> int:
        return self._c._call({"op": "tick"})["tick"]

    def partition(self, stream: str, from_tick: int, to_tick: int, mode: str = "drop") -> None:
        self._c._call({"op": "partition", "cmd": {"op": "partition", "deployment": stream, "from_tick": from_tick,
                                                  "to_tick": to_tick, "mode": mode}})

    def clear_faults(self) -> None:
        self._c._call({"op": "clear_faults"})

    def fault_log(self) -> dict:
        r = self._c._call({"op": "fault_log"})
        return {"log": r["log"], "windows": r["windows"]}


class AnchorProcess:
    def __init__(self, proc: subprocess.Popen, anchor_dir: str, sock_path: str):
        self.proc, self.pid, self.anchor_dir, self.sock_path = proc, proc.pid, str(anchor_dir), str(sock_path)
        self.ctl_path = self.sock_path + ".ctl"

    def control(self) -> AnchorControl:
        return AnchorControl(self.ctl_path)

    def client(self) -> AnchorClient:
        return AnchorClient(self.sock_path)

    def close(self) -> dict:
        """Reveal the key (KEY.revealed) after the last append; returns {"key": hex, "head": {...}} as reported over the socket."""
        try:
            resp = AnchorClient(self.sock_path)._call({"op": "close"})
        finally:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return {"key": resp["key"], "head": resp["head"]}


def start_anchor(anchor_dir, sock_path, control: bool = False) -> AnchorProcess:
    """Harness/runner only: start the anchor as a separate OS process (E1). Refuses an anchor dir that already has a log."""
    Path(anchor_dir).mkdir(parents=True, exist_ok=True)
    if (Path(anchor_dir) / LOG_NAME).exists():
        raise AnchorError("anchor dir already holds a log")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = subprocess.Popen([sys.executable, "-m", "r3_shared.anchor_server", "--dir", str(anchor_dir), "--sock", str(sock_path)] + (["--control"] if control else []),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    line = proc.stdout.readline()
    if not line.startswith(b"READY"):
        proc.kill()
        raise AnchorError(f"anchor failed to start: {proc.stderr.read().decode(errors='replace')[:500]}")
    return AnchorProcess(proc, anchor_dir, sock_path)


def verify_anchor_log(anchor_dir, key: bytes | None = None, expected_head: dict | None = None) -> dict:
    """Pure evaluator check (E5): hash chain + per-entry HMAC (key from KEY.revealed unless given) + gap-free per-stream seq
    + final head equals HEAD.final (and `expected_head`, the head the anchor reported at close, when given)."""
    d, errors = Path(anchor_dir), []
    lp = d / LOG_NAME
    raw = lp.read_bytes() if lp.exists() else b""
    lines = raw.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    elif lines:
        errors.append("log does not end with a newline (truncated line)")
    if key is None and (d / KEY_NAME).exists():
        key = bytes.fromhex((d / KEY_NAME).read_text().strip())
    prev, streams, chain_ok, mac_ok = ZERO, {}, True, key is not None
    if key is None:
        errors.append("key not revealed: MACs unverifiable")
    for n, line in enumerate(lines):
        try:
            e = json.loads(line)
        except ValueError:
            errors.append(f"line {n}: not JSON")
            chain_ok = False
            continue
        if not isinstance(e, dict):
            errors.append(f"line {n}: not a JSON object")
            chain_ok = False
            prev = line_sha(line)
            continue
        if e.get("i") != n or e.get("prev_entry") != prev:
            errors.append(f"line {n}: chain break (i/prev_entry mismatch)")
            chain_ok = False
        if key is not None and not hmac.compare_digest(str(e.get("mac")), entry_mac(key, e)):
            errors.append(f"line {n}: bad MAC")
            mac_ok = False
        if not isinstance(e.get("seq"), int) or isinstance(e.get("seq"), bool):
            errors.append(f"line {n}: seq missing or not an int")
            chain_ok = False
            prev = line_sha(line)
            continue
        if not isinstance(e.get("stream"), (str, int, type(None))):
            errors.append(f"line {n}: stream is not a scalar")
            chain_ok = False
            prev = line_sha(line)
            continue
        if e.get("seq") != streams.get(e.get("stream"), 0) + 1:
            errors.append(f"line {n}: stream seq gap/duplicate")
            chain_ok = False
        streams[e.get("stream")] = e.get("seq")
        prev = line_sha(line)
    head = {"entries": len(lines), "last_entry_sha": prev}
    head_ok = True
    for name, ref in (("HEAD.final", json.loads((d / HEAD_NAME).read_text()) if (d / HEAD_NAME).exists() else None),
                      ("expected_head", expected_head)):
        if ref is None:
            if name == "HEAD.final":
                errors.append("HEAD.final missing")
                head_ok = False
        elif (ref.get("entries"), ref.get("last_entry_sha")) != (head["entries"], head["last_entry_sha"]):
            errors.append(f"final head differs from {name}")
            head_ok = False
    return {"ok": not errors and chain_ok and mac_ok and head_ok, "chain_ok": chain_ok, "mac_ok": mac_ok,
            "head_ok": head_ok, "entries": len(lines), "head": head, "errors": errors}


def close_anchor(sock_path) -> dict:
    """Close an anchor by socket (runner use): reveals the key, returns {"key", "head"}."""
    r = AnchorClient(str(sock_path))._call({"op": "close"})
    return {"key": r["key"], "head": r["head"]}


def require_anchor(exp_id: str, env=None) -> tuple[str, str]:
    """G3-E31b pattern for the H29 runner: a non-dev experiment id REFUSES to run unless the launcher started the anchor
    (R3_ANCHOR_SOCK and R3_ANCHOR_DIR set and the socket answers a ping). Returns (sock, dir). Dev ids without a configured
    anchor get AnchorError too; the caller may then start its own (start_anchor)."""
    env = os.environ if env is None else env
    sock, d = env.get("R3_ANCHOR_SOCK"), env.get("R3_ANCHOR_DIR")
    if not (sock and d):
        raise AnchorError(f"refusing: experiment id {exp_id!r} requires R3_ANCHOR_SOCK/R3_ANCHOR_DIR (launch through the H29 launcher "
                          "so the anchor runs outside the sandbox)" if "-dev" not in exp_id else "no anchor configured (dev id: start one with start_anchor)")
    try:
        AnchorClient(sock)._call({"op": "ping"})
    except AnchorError as exc:
        raise AnchorError(f"refusing: anchor at {sock} is not running: {exc}") from exc
    return sock, d
