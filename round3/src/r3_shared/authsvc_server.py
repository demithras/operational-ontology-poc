"""AuthorityService process (PROTOCOL-P1g P1g-2): `python -m r3_shared.authsvc_server --dir <auth_dir> --socket <path>`.
HARNESS ONLY - variant packages must not import this module (import scan). Two Unix sockets:
  <path>      DATA plane (variant): fetch, ping
  <path>.ctl  CONTROL plane (harness only): publish, advance, tick, outage, log, close, ping
Owns <auth_dir>/authority.db (WAL while live, DELETE at close - G4-E13) and an HMAC key from os.urandom, revealed at close."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import socketserver
import sqlite3
import sys
import threading
from pathlib import Path

DB_NAME, KEY_NAME, HEAD_NAME = "authority.db", "KEY.revealed", "HEAD.final"
DATA_OPS = ("fetch", "ping")
CONTROL_OPS = ("publish", "advance", "tick", "outage", "log", "close", "ping")
_DDL = """
CREATE TABLE versions(seq INTEGER PRIMARY KEY AUTOINCREMENT, digest TEXT NOT NULL, doc_json TEXT NOT NULL,
  requested_tick INTEGER NOT NULL, effective_tick INTEGER NOT NULL);
CREATE TABLE leases(seq INTEGER PRIMARY KEY AUTOINCREMENT, deployment TEXT NOT NULL, digest TEXT NOT NULL,
  granted_tick INTEGER NOT NULL, lease_until INTEGER NOT NULL, mac TEXT NOT NULL);
CREATE TABLE faults(seq INTEGER PRIMARY KEY AUTOINCREMENT, deployment TEXT NOT NULL, kind TEXT NOT NULL,
  from_tick INTEGER NOT NULL, to_tick INTEGER NOT NULL, mode TEXT NOT NULL);
CREATE TABLE refused(seq INTEGER PRIMARY KEY AUTOINCREMENT, tick INTEGER NOT NULL, deployment TEXT NOT NULL,
  op TEXT NOT NULL, reason TEXT NOT NULL);
"""


def canon(x) -> str:
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def lease_mac(key: bytes, deployment: str, digest: str, granted_tick: int, lease_until: int) -> str:
    msg = canon({"deployment": deployment, "digest": digest, "granted_tick": granted_tick, "lease_until": lease_until})
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


class Unavail(Exception):
    """Internal: a drop window covers the fetch."""


class Core:
    def __init__(self, auth_dir: Path, lease: int):
        self.dir, self.lease, self.tick, self.closed = auth_dir, lease, 0, False
        self.key, self.lock = os.urandom(32), threading.RLock()
        db = auth_dir / DB_NAME
        if db.exists():
            raise FileExistsError(f"{db} already exists: refusing to reuse an authority log")
        self.con = sqlite3.connect(str(db), isolation_level=None, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(_DDL)

    # ---- lease rule (P1g-2, normative) -----------------------------------------------------------------------------
    def publish(self, doc) -> dict:
        if not isinstance(doc, dict):
            raise ValueError("authority document must be a JSON object")
        digest = hashlib.sha256(canon(doc).encode()).hexdigest()
        p = self.tick
        # f = max(p, latest lease_until granted for an OLDER digest); kept monotone over earlier versions (publish order = effect order)
        lu = self.con.execute("SELECT COALESCE(MAX(lease_until),0) FROM leases WHERE digest<>?", (digest,)).fetchone()[0]
        prev = self.con.execute("SELECT COALESCE(MAX(effective_tick),0) FROM versions").fetchone()[0]
        f = max(p, lu, prev)
        self.con.execute("INSERT INTO versions(digest,doc_json,requested_tick,effective_tick) VALUES(?,?,?,?)",
                         (digest, canon(doc), p, f))
        return {"digest": digest, "effective_tick": f}

    def in_force(self, t: int):
        return self.con.execute("SELECT digest, doc_json FROM versions WHERE effective_tick<=? ORDER BY effective_tick DESC, seq DESC LIMIT 1",
                                (t,)).fetchone()

    def window(self, dep: str):
        r = self.con.execute("SELECT kind, mode, from_tick, to_tick FROM faults WHERE deployment=? AND from_tick<=? AND ?<to_tick "
                             "ORDER BY seq LIMIT 1", (dep, self.tick, self.tick)).fetchone()
        return r

    def fetch(self, dep: str) -> dict:
        t = self.tick
        w = self.window(dep)
        if w is not None and w[1] == "drop":
            self.con.execute("INSERT INTO refused(tick,deployment,op,reason) VALUES(?,?,?,?)", (t, dep, "fetch", f"{w[0]}:drop"))
            raise Unavail()
        cur = self.in_force(t)
        if cur is None:
            raise ValueError("no authority version published")
        pend = self.con.execute("SELECT MIN(effective_tick) FROM versions WHERE effective_tick>? AND requested_tick<=?", (t, t)).fetchone()[0]
        until = t + self.lease if pend is None else min(t + self.lease, pend)
        mac = lease_mac(self.key, dep, cur[0], t, until)
        self.con.execute("INSERT INTO leases(deployment,digest,granted_tick,lease_until,mac) VALUES(?,?,?,?,?)", (dep, cur[0], t, until, mac))
        return {"lease": {"digest": cur[0], "doc": json.loads(cur[1]), "granted_tick": t, "lease_until": until, "mac": mac},
                "reply_lost": w is not None}

    def outage(self, cmd: dict) -> None:
        from r3_shared.faultplane import validate_fault_command
        validate_fault_command(cmd)
        if "target" in cmd:
            raise ValueError("AuthorityService fault commands carry no target")
        self.con.execute("INSERT INTO faults(deployment,kind,from_tick,to_tick,mode) VALUES(?,?,?,?,?)",
                         (cmd["deployment"], cmd["op"], cmd["from_tick"], cmd["to_tick"], cmd["mode"]))

    def log(self) -> dict:
        def rows(table, cols):
            return [dict(zip(cols, r)) for r in self.con.execute(f"SELECT {','.join(cols)} FROM {table} ORDER BY seq")]
        v = rows("versions", ("seq", "digest", "doc_json", "requested_tick", "effective_tick"))
        for r in v:
            r["doc"] = json.loads(r.pop("doc_json"))
        return {"versions": v, "leases": rows("leases", ("seq", "deployment", "digest", "granted_tick", "lease_until", "mac")),
                "faults": rows("faults", ("seq", "deployment", "kind", "from_tick", "to_tick", "mode")),
                "refused": rows("refused", ("seq", "tick", "deployment", "op", "reason"))}

    def close(self) -> dict:
        self.closed = True
        lg = self.log()
        head = {"versions": len(lg["versions"]), "leases": len(lg["leases"]), "faults": len(lg["faults"]),
                "refused": len(lg["refused"]), "log_sha256": hashlib.sha256(canon(lg).encode()).hexdigest()}
        self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.con.execute("PRAGMA journal_mode=DELETE")
        self.con.close()
        (self.dir / HEAD_NAME).write_text(json.dumps(head))
        (self.dir / KEY_NAME).write_text(self.key.hex())
        return {"key_hex": self.key.hex(), "head": head}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        core, plane = self.server.core, self.server.plane
        stop_after_reply = False
        try:
            r = json.loads(self.rfile.readline())
            op = r.get("op")
            if op not in (DATA_OPS if plane == "data" else CONTROL_OPS):
                raise ValueError(f"op {op!r} is not available on the {plane} plane")
            with core.lock:
                if core.closed:
                    raise ValueError("authority service closed")
                if op == "ping":
                    out = {"pid": os.getpid(), "plane": plane}
                elif op == "fetch":
                    got = core.fetch(r["deployment"])
                    if got["reply_lost"]:  # lease granted and logged, reply dropped (connection closed unanswered)
                        return
                    out = {"lease": got["lease"]}
                elif op == "publish":
                    out = core.publish(r["doc"])
                elif op == "advance":
                    if not isinstance(r.get("tick"), int) or isinstance(r.get("tick"), bool) or r["tick"] < core.tick:
                        raise ValueError(f"tick must be an int >= current tick {core.tick}")
                    core.tick = r["tick"]
                    out = {"tick": core.tick}
                elif op == "tick":
                    out = {"tick": core.tick}
                elif op == "outage":
                    core.outage(r["cmd"])
                    out = {}
                elif op == "log":
                    out = {"log": core.log()}
                else:  # close
                    out = core.close()
                    stop_after_reply = True
            resp = {"ok": True, **out}
        except Unavail:
            resp = {"ok": False, "error": "unavailable", "unavailable": True}
        except Exception as exc:  # protocol-level refusal; never crash the service
            resp = {"ok": False, "error": str(exc)}
        self.wfile.write(canon(resp).encode() + b"\n")
        self.wfile.flush()
        if stop_after_reply:
            # flush the close reply BEFORE shutdown (anchor/ExternalWorld G4 lesson): else the key is lost under load
            threading.Thread(target=self.server.stop, daemon=True).start()


class PlaneServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, path, core, plane, stop):
        if os.path.exists(path):
            os.unlink(path)
        self.core, self.plane, self.stop = core, plane, stop
        super().__init__(path, Handler)
        os.chmod(path, 0o600)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--socket", required=True)
    ap.add_argument("--lease", type=int, default=4, help="LEASE in ticks (envelope-ops.json constants.LEASE)")
    a = ap.parse_args(argv)
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    core = Core(d, a.lease)
    done = threading.Event()
    data, ctl = PlaneServer(a.socket, core, "data", done.set), PlaneServer(a.socket + ".ctl", core, "control", done.set)
    for s in (data, ctl):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    print(f"READY {os.getpid()}", flush=True)
    done.wait()
    for s in (data, ctl):
        s.shutdown()
        s.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
