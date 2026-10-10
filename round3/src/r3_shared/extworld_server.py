"""ExternalWorld service process: `python -m r3_shared.extworld_server --dir <ext_dir> --systems <systems.json> --socket <path>`.
HARNESS ONLY - variant packages must not import this module (import scan test_p1f_boundaries). Two Unix sockets:
  <path>      DATA plane (adapters): write, ping
  <path>.ctl  CONTROL plane (harness only): issue_root, advance, observer_key, seed, tick, close, ping
The root key is os.urandom(32), in memory only, revealed by close() (KEY.revealed + close output)."""
from __future__ import annotations

import argparse
import json
import os
import socketserver
import sys
import threading

from r3_shared.extadapter import canon_json
from r3_shared.extworld_core import ExternalWorldCore

DATA_OPS = ("write", "ping")
CONTROL_OPS = ("issue_root", "advance", "observer_key", "seed", "tick", "close", "ping")


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        core, plane = self.server.core, self.server.plane
        stop_after_reply = False
        try:
            r = json.loads(self.rfile.readline())
            op = r.get("op")
            if op not in (DATA_OPS if plane == "data" else CONTROL_OPS):
                raise ValueError(f"op {op!r} is not available on the {plane} plane")
            if op == "ping":
                out = {"pid": os.getpid(), "plane": plane}
            elif op == "write":
                out = {"receipt": core.write(r["cap"], r["operation"], r["target"], r["payload"], r["adapter_id"])}
            elif op == "issue_root":
                out = {"cap": core.issue_root(r["deployment"], r["system"])}
            elif op == "advance":
                out = {"tick": core.advance(r["tick"])}
            elif op == "observer_key":
                out = {"key": core.observer_key(r["deployment"])}
            elif op == "seed":
                core.seed(r["system"], r["key"], r["props"])
                out = {}
            elif op == "tick":
                out = {"tick": core.tick}
            else:  # close
                out = core.close()
                stop_after_reply = True
            resp = {"ok": True, **out}
        except Exception as exc:  # protocol-level refusal; never crash the service
            resp = {"ok": False, "error": str(exc)}
        self.wfile.write(canon_json(resp).encode() + b"\n")
        self.wfile.flush()
        if stop_after_reply:
            # Only now release main(): stopping before the reply was flushed let the process exit (daemon handler thread
            # killed) so the client read an EMPTY close reply, losing the revealed root key, under load.
            threading.Thread(target=self.server.stop, daemon=True).start()


class PlaneServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = False  # server_close() joins handler threads: the close reply is fully sent before the process exits
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
    ap.add_argument("--systems", required=True)
    ap.add_argument("--socket", required=True)
    a = ap.parse_args(argv)
    core = ExternalWorldCore(a.dir, json.loads(open(a.systems).read()))
    done = threading.Event()
    data = PlaneServer(a.socket, core, "data", done.set)
    ctl = PlaneServer(a.socket + ".ctl", core, "control", done.set)
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
