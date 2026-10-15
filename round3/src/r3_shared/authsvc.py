"""AuthorityService client + harness-side process management + strict forms (PROTOCOL-P1g P1g-2). The DATA plane
(AuthorityClient.fetch) is what a variant may import; the control plane (publish, advance, outage, log, close) needs the
control socket path, which only the harness holds. Wire: one canonical-JSON object per line, one request per connection."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import socket
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import jsonschema

from .faultplane import DependencyUnavailable, validate_fault_command

ROUND3 = Path(__file__).resolve().parents[2]
DB_NAME, KEY_NAME, HEAD_NAME = "authority.db", "KEY.revealed", "HEAD.final"
_LEASE_SCHEMA = json.loads((ROUND3 / "schemas" / "lease-grant.schema.json").read_text())
_LOG_SCHEMA = json.loads((ROUND3 / "schemas" / "authority-log.schema.json").read_text())


class AuthorityError(Exception):
    """The AuthorityService refused a request, is unreachable, replied malformed, or the launcher guard refused."""


class AuthorityUnavailable(AuthorityError, DependencyUnavailable):
    """Server-side outage/partition window (drop) or a reply dropped (reply_lost). str(e) == "AUTH"."""

    def __init__(self, detail: str = ""):
        DependencyUnavailable.__init__(self, "AUTH")
        self.detail = detail


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def doc_digest(doc: dict) -> str:
    """sha256 hex of the canonical JSON of an authority document (equals Deployment.authority_version())."""
    return hashlib.sha256(canon(doc).encode()).hexdigest()


def lease_mac(key: bytes, deployment: str, digest: str, granted_tick: int, lease_until: int) -> str:
    msg = canon({"deployment": deployment, "digest": digest, "granted_tick": granted_tick, "lease_until": lease_until})
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Lease:
    digest: str
    doc: dict
    granted_tick: int
    lease_until: int
    mac: str

    def valid_at(self, tick: int) -> bool:
        """P1g-2: granted_tick <= t < lease_until (strict upper bound)."""
        return self.granted_tick <= tick < self.lease_until


def validate_lease(d: dict) -> Lease:
    """Strict form (schemas/lease-grant.schema.json) + bool rejection + digest binds the doc. ValueError on violation."""
    try:
        jsonschema.validate(d, _LEASE_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"lease: {exc.message}") from exc
    if isinstance(d["granted_tick"], bool) or isinstance(d["lease_until"], bool):
        raise ValueError("lease: bool where int expected")
    if d["lease_until"] <= d["granted_tick"]:
        raise ValueError("lease: lease_until must exceed granted_tick")
    if doc_digest(d["doc"]) != d["digest"]:
        raise ValueError("lease: digest does not match doc")
    return Lease(d["digest"], d["doc"], d["granted_tick"], d["lease_until"], d["mac"])


def validate_log(lg: dict) -> dict:
    """Strict form of AuthorityControl.log(); also: seq strictly increasing per table, digests match docs, effective >= requested,
    every lease/version digest known. ValueError on violation. Returns lg."""
    try:
        jsonschema.validate(lg, _LOG_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"authority log: {exc.message}") from exc
    for t in ("versions", "leases", "faults", "refused"):
        seqs = [r["seq"] for r in lg[t]]
        if seqs != sorted(set(seqs)):
            raise ValueError(f"authority log: {t} seq not strictly increasing")
        if any(isinstance(v, bool) for r in lg[t] for v in r.values()):
            raise ValueError(f"authority log: bool value in {t}")
    known = set()
    for v in lg["versions"]:
        if doc_digest(v["doc"]) != v["digest"]:
            raise ValueError("authority log: version digest does not match doc")
        if v["effective_tick"] < v["requested_tick"]:
            raise ValueError("authority log: effective_tick before requested_tick")
        known.add(v["digest"])
    for l in lg["leases"]:
        if l["digest"] not in known or l["lease_until"] <= l["granted_tick"]:
            raise ValueError("authority log: lease with unknown digest or empty window")
    for f in lg["faults"]:
        validate_fault_command({"op": f["kind"], "deployment": f["deployment"], "from_tick": f["from_tick"], "to_tick": f["to_tick"], "mode": f["mode"]})
    return lg


def in_force(versions: list[dict], tick: int) -> str | None:
    """A(t) from the log's versions: digest with the greatest effective_tick <= t (ties: greatest seq)."""
    best = None
    for v in versions:
        if v["effective_tick"] <= tick and (best is None or (v["effective_tick"], v["seq"]) > (best["effective_tick"], best["seq"])):
            best = v
    return None if best is None else best["digest"]


def verify_log(auth_dir, key_hex: str | None = None) -> dict:
    """Post-close check by the evaluator: every lease MAC verifies under the revealed key, the log passes validate_log, and its
    hash equals HEAD.final. Returns {"ok", "errors", "log"}."""
    d, errors = Path(auth_dir), []
    key = bytes.fromhex(key_hex or (d / KEY_NAME).read_text().strip()) if (key_hex or (d / KEY_NAME).exists()) else None
    if key is None:
        return {"ok": False, "errors": ["key not revealed"], "log": None}
    con = sqlite3.connect(f"file:{d / DB_NAME}?mode=ro", uri=True)
    try:
        def rows(t, cols):
            return [dict(zip(cols, r)) for r in con.execute(f"SELECT {','.join(cols)} FROM {t} ORDER BY seq")]
        lg = {"versions": rows("versions", ("seq", "digest", "doc_json", "requested_tick", "effective_tick")),
              "leases": rows("leases", ("seq", "deployment", "digest", "granted_tick", "lease_until", "mac")),
              "faults": rows("faults", ("seq", "deployment", "kind", "from_tick", "to_tick", "mode")),
              "refused": rows("refused", ("seq", "tick", "deployment", "op", "reason"))}
    finally:
        con.close()
    for v in lg["versions"]:
        v["doc"] = json.loads(v.pop("doc_json"))
    try:
        validate_log(lg)
    except ValueError as exc:
        errors.append(str(exc))
    for l in lg["leases"]:
        if not hmac.compare_digest(l["mac"], lease_mac(key, l["deployment"], l["digest"], l["granted_tick"], l["lease_until"])):
            errors.append(f"lease {l['seq']}: bad MAC")
    head_p = d / HEAD_NAME
    if not head_p.exists():
        errors.append("HEAD.final missing")
    elif json.loads(head_p.read_text()).get("log_sha256") != hashlib.sha256(canon(lg).encode()).hexdigest():
        errors.append("log hash differs from HEAD.final")
    return {"ok": not errors, "errors": errors, "log": lg}


def _call(path: str, req: dict, timeout: float = 15.0) -> dict:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall(canon(req).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        if buf == b"":  # closed without a reply: reply_lost window
            raise AuthorityUnavailable("connection closed without a reply")
        resp = json.loads(buf)
    except (OSError, ValueError) as exc:
        raise AuthorityError(f"authority service unreachable: {exc}") from exc
    if not resp.get("ok"):
        if resp.get("unavailable"):
            raise AuthorityUnavailable("authority partitioned")
        raise AuthorityError(resp.get("error", "authority service error"))
    return resp


class AuthorityClient:
    """Data plane only (what a variant holds). Bound to one deployment id."""

    def __init__(self, sock: str, deployment_id: str, timeout: float = 15.0):
        self._sock, self.deployment_id, self._timeout = str(sock), deployment_id, timeout

    def fetch(self) -> Lease:
        """Fetch/renew the lease for this deployment at the server tick. AuthorityUnavailable (== DependencyUnavailable("AUTH"))
        under an outage/partition window."""
        r = _call(self._sock, {"op": "fetch", "deployment": self.deployment_id}, self._timeout)
        try:
            return validate_lease(r["lease"])
        except (KeyError, ValueError) as exc:
            raise AuthorityError(f"malformed lease reply: {exc}") from exc

    def ping(self) -> dict:
        return _call(self._sock, {"op": "ping"}, self._timeout)


class AuthorityControl:
    """Control plane (harness only)."""

    def __init__(self, ctl: str, timeout: float = 15.0):
        self._ctl, self._timeout = str(ctl), timeout

    def _c(self, req: dict) -> dict:
        return _call(self._ctl, req, self._timeout)

    def publish(self, doc: dict) -> str:
        return self._c({"op": "publish", "doc": doc})["digest"]

    def publish_info(self, doc: dict) -> dict:
        r = self._c({"op": "publish", "doc": doc})
        return {"digest": r["digest"], "effective_tick": r["effective_tick"]}

    def advance(self, tick: int) -> int:
        return self._c({"op": "advance", "tick": tick})["tick"]

    def tick(self) -> int:
        return self._c({"op": "tick"})["tick"]

    def outage(self, deployment: str, from_tick: int, to_tick: int, mode: str = "drop") -> None:
        self._c({"op": "outage", "cmd": {"op": "outage", "deployment": deployment, "from_tick": from_tick, "to_tick": to_tick, "mode": mode}})

    def partition(self, deployment: str, from_tick: int, to_tick: int, mode: str = "drop") -> None:
        self._c({"op": "outage", "cmd": {"op": "partition", "deployment": deployment, "from_tick": from_tick, "to_tick": to_tick, "mode": mode}})

    def log(self) -> dict:
        return validate_log(self._c({"op": "log"})["log"])

    def close(self) -> dict:
        r = self._c({"op": "close"})
        return {"key_hex": r["key_hex"], "head": r["head"]}


class AuthorityProcess:
    def __init__(self, proc: subprocess.Popen, auth_dir: str, sock: str):
        self.proc, self.pid, self.auth_dir = proc, proc.pid, str(auth_dir)
        self.sock_path, self.ctl_path = str(sock), str(sock) + ".ctl"

    def client(self, deployment_id: str) -> AuthorityClient:
        return AuthorityClient(self.sock_path, deployment_id)

    def control(self) -> AuthorityControl:
        return AuthorityControl(self.ctl_path)

    def close(self) -> dict:
        try:
            return self.control().close()
        finally:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def start_authority(auth_dir, sock_path, lease: int = 4) -> AuthorityProcess:
    """Harness/runner only: start the AuthorityService as a separate OS process. Refuses a dir that already holds a log."""
    Path(auth_dir).mkdir(parents=True, exist_ok=True)
    if (Path(auth_dir) / DB_NAME).exists():
        raise AuthorityError("authority dir already holds a log")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1]) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    proc = subprocess.Popen([sys.executable, "-m", "r3_shared.authsvc_server", "--dir", str(auth_dir), "--socket", str(sock_path),
                             "--lease", str(lease)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    line = proc.stdout.readline()
    if not line.startswith(b"READY"):
        proc.kill()
        raise AuthorityError(f"authority service failed to start: {proc.stderr.read().decode(errors='replace')[:500]}")
    return AuthorityProcess(proc, auth_dir, sock_path)


def is_dev_id(exp_id: str) -> bool:
    return "-dev" in exp_id


def require_authority(exp_id: str, env=None) -> tuple[str, str, str]:
    """G3-E31b pattern: a non-dev experiment id REFUSES to run unless the launcher started the AuthorityService
    (R3_AUTH_SOCK, R3_AUTH_CTL, R3_AUTH_DIR set and the data socket answers). Returns (sock, ctl, dir)."""
    env = os.environ if env is None else env
    sock, ctl, d = env.get("R3_AUTH_SOCK"), env.get("R3_AUTH_CTL"), env.get("R3_AUTH_DIR")
    if not (sock and ctl and d):
        raise AuthorityError(f"refusing: experiment id {exp_id!r} requires R3_AUTH_SOCK/R3_AUTH_CTL/R3_AUTH_DIR "
                             "(launch through the H29 launcher so the AuthorityService runs outside the sandbox)"
                             if not is_dev_id(exp_id) else "no AuthorityService configured (dev id: start one with start_authority)")
    try:
        AuthorityClient(sock, "probe").ping()
    except AuthorityError as exc:
        raise AuthorityError(f"refusing: AuthorityService at {sock} is not running: {exc}") from exc
    return sock, ctl, d
