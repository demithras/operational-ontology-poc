"""Anchor service process: `python -m r3_shared.anchor_server --dir <anchor_dir> --sock <path>`. HARNESS ONLY - the
variant packages must not import this module (import scan). Key = os.urandom(32), in memory only, revealed at close."""
from __future__ import annotations

import argparse
import json
import os
import socketserver
import sys
import threading
from pathlib import Path

from r3_shared.anchor import HEAD_NAME, KEY_NAME, LOG_NAME, ZERO, canon, entry_mac, line_sha


class State:
    def __init__(self, d: Path):
        self.dir, self.key, self.lock = d, os.urandom(32), threading.Lock()
        self.fd = os.open(str(d / LOG_NAME), os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_EXCL, 0o644)
        self.i, self.prev = 0, ZERO
        self.by_seq: dict[tuple[str, int], dict] = {}
        self.by_dec: dict[tuple[str, str], dict] = {}
        self.heads: dict[str, dict] = {}
        self.closed = False
        self.tick, self.faults, self.fault_log = 0, [], []  # G5 (P1g-3): server tick + partition windows + activation log

    def window(self, stream):
        for w in self.faults:
            if w["deployment"] == stream and w["from_tick"] <= self.tick < w["to_tick"]:
                return w
        return None

    def head_all(self) -> dict:
        return {"entries": self.i, "last_entry_sha": self.prev}

    def append(self, r: dict) -> dict:
        stream, seq, dec, root = r.get("stream"), r.get("seq"), r.get("decision_id"), r.get("root")
        if not (isinstance(stream, str) and isinstance(dec, str) and isinstance(root, str)
                and isinstance(seq, int) and not isinstance(seq, bool)):
            raise ValueError("malformed append")
        h = self.heads.get(stream)
        if (stream, seq) in self.by_seq:
            raise ValueError(f"duplicate append for ({stream}, {seq})")
        if seq != (h["seq"] if h else 0) + 1:
            raise ValueError(f"seq gap: {seq} != head+1 for {stream}")
        e = {"stream": stream, "seq": seq, "decision_id": dec, "root": root, "prev_entry": self.prev, "i": self.i}
        e["mac"] = entry_mac(self.key, e)
        line = canon(e)
        os.write(self.fd, line + b"\n")
        os.fsync(self.fd)
        self.prev, self.i = line_sha(line), self.i + 1
        self.by_seq[(stream, seq)], self.heads[stream] = e, e
        self.by_dec.setdefault((stream, dec), e)
        return e

    def close(self) -> dict:
        os.close(self.fd)
        head = self.head_all()
        (self.dir / HEAD_NAME).write_text(json.dumps(head))
        (self.dir / KEY_NAME).write_text(self.key.hex())
        self.closed = True
        return {"key": self.key.hex(), "head": head}


class Unavail(Exception):
    """Internal: a drop window covers the call; the client sees `unavailable`."""


DATA_OPS = ("append", "get", "lookup", "head", "close", "ping")
CONTROL_OPS = ("advance", "tick", "partition", "clear_faults", "fault_log", "ping")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        st: State = self.server.st
        shutdown_after_reply = False
        try:
            r = json.loads(self.rfile.readline())
            with st.lock:
                if st.closed:
                    raise ValueError("anchor closed")
                op = r.get("op")
                if getattr(self.server, "plane", "data") == "control":
                    out = self.control(st, op, r)
                    self.wfile.write(canon({"ok": True, **out}) + b"\n")
                    self.wfile.flush()
                    return
                w = st.window(r.get("stream")) if st.faults and op in ("append", "get", "lookup", "head") else None
                if w is not None and w["mode"] == "drop":
                    st.fault_log.append({"tick": st.tick, "stream": r.get("stream"), "op": op, "mode": "drop", "applied": False})
                    raise Unavail()
                if w is not None:  # reply_lost: reads/appends are applied (and logged), then the connection is closed unanswered
                    if op == "append":
                        st.append(r)
                    st.fault_log.append({"tick": st.tick, "stream": r.get("stream"), "op": op, "mode": "reply_lost",
                                         "applied": op == "append"})
                    return  # no reply written: the client sees a closed connection -> AnchorUnavailable
                if op not in DATA_OPS:
                    raise ValueError(f"unknown op {op!r}")
                if op == "append":
                    out = {"entry": st.append(r)}
                elif op == "get":
                    out = {"entry": st.by_seq.get((r.get("stream"), r.get("seq")))}
                elif op == "lookup":
                    out = {"entry": st.by_dec.get((r.get("stream"), r.get("decision_id")))}
                elif op == "head":
                    out = {"entry": st.heads.get(r.get("stream"))}
                elif op == "close":
                    out = st.close()
                    shutdown_after_reply = True
                elif op == "ping":
                    out = {"pid": os.getpid()}
                else:
                    raise ValueError(f"unknown op {op!r}")
            resp = {"ok": True, **out}
        except Unavail:
            resp = {"ok": False, "error": "unavailable", "unavailable": True}
        except Exception as exc:  # protocol-level refusal; never crash the service
            resp = {"ok": False, "error": str(exc)}
        self.wfile.write(canon(resp) + b"\n")
        self.wfile.flush()
        if shutdown_after_reply:
            # Only now stop the server: shutting down before the reply was flushed let main() exit (daemon handler thread
            # killed) so the client read an EMPTY close reply under load.
            threading.Thread(target=self.server.shutdown, daemon=True).start()


    @staticmethod
    def control(st: State, op, r: dict) -> dict:
        from r3_shared.faultplane import validate_fault_command
        if op == "advance":
            if not isinstance(r.get("tick"), int) or isinstance(r.get("tick"), bool) or r["tick"] < st.tick:
                raise ValueError(f"tick must be an int >= current tick {st.tick}")
            st.tick = r["tick"]
            return {"tick": st.tick}
        if op == "tick":
            return {"tick": st.tick}
        if op == "partition":
            cmd = validate_fault_command(r["cmd"])
            if cmd["op"] != "partition":
                raise ValueError("anchor accepts partition commands only")
            st.faults.append(dict(cmd))
            return {"n": len(st.faults)}
        if op == "clear_faults":
            st.faults = []
            return {}
        if op == "fault_log":
            return {"log": list(st.fault_log), "windows": list(st.faults)}
        if op == "ping":
            return {"pid": os.getpid(), "plane": "control"}
        raise ValueError(f"op {op!r} is not available on the control plane")


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = False  # server_close() joins handler threads: the close reply is fully sent before the process exits
    block_on_close = True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--sock", required=True)
    ap.add_argument("--control", action="store_true", help="G5: also serve the control plane on <sock>.ctl")
    a = ap.parse_args(argv)
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    st = State(d)
    if os.path.exists(a.sock):
        os.unlink(a.sock)
    srv = Server(a.sock, Handler)
    srv.st = st
    os.chmod(a.sock, 0o600)
    ctl = None
    if a.control:
        if os.path.exists(a.sock + ".ctl"):
            os.unlink(a.sock + ".ctl")
        ctl = Server(a.sock + ".ctl", Handler)
        ctl.st, ctl.plane = st, "control"
        os.chmod(a.sock + ".ctl", 0o600)
        threading.Thread(target=ctl.serve_forever, daemon=True).start()
    print(f"READY {os.getpid()}", flush=True)
    srv.serve_forever()
    srv.server_close()
    if ctl is not None:
        ctl.shutdown()
        ctl.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
