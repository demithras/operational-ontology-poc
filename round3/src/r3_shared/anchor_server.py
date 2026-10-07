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


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        st: State = self.server.st
        try:
            r = json.loads(self.rfile.readline())
            with st.lock:
                if st.closed:
                    raise ValueError("anchor closed")
                op = r.get("op")
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
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                elif op == "ping":
                    out = {"pid": os.getpid()}
                else:
                    raise ValueError(f"unknown op {op!r}")
            resp = {"ok": True, **out}
        except Exception as exc:  # protocol-level refusal; never crash the service
            resp = {"ok": False, "error": str(exc)}
        self.wfile.write(canon(resp) + b"\n")


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--sock", required=True)
    a = ap.parse_args(argv)
    d = Path(a.dir)
    d.mkdir(parents=True, exist_ok=True)
    st = State(d)
    if os.path.exists(a.sock):
        os.unlink(a.sock)
    srv = Server(a.sock, Handler)
    srv.st = st
    os.chmod(a.sock, 0o600)
    print(f"READY {os.getpid()}", flush=True)
    srv.serve_forever()
    srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
