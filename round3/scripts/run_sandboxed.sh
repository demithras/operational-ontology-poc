#!/bin/bash
# run_sandboxed.sh <anchor_dir> <cmd...>   (PROT-H27 s4 E1/E3; PROTOCOL-P1d P1d-8)
# Starts the anchor service OUTSIDE the sandbox (separate OS process), then runs <cmd> under macOS sandbox-exec with a
# profile denying file-write* on <anchor_dir>. <cmd> sees R3_ANCHOR_SOCK (Unix socket) and R3_ANCHOR_DIR (for the E4
# probe / E5 verification only). After <cmd> exits the anchor is closed (key revealed) and <cmd>'s exit code returned.
set -u
[ $# -ge 2 ] || { echo "usage: run_sandboxed.sh <anchor_dir> <cmd...>" >&2; exit 64; }
command -v sandbox-exec >/dev/null 2>&1 || { echo "run_sandboxed: sandbox-exec unavailable - refusing to run unsandboxed" >&2; exit 69; }
HERE="$(cd "$(dirname "$0")/.." && pwd -P)"
PY="${PY:-$HERE/.venv/bin/python}"; [ -x "$PY" ] || PY="$(command -v python3)"
mkdir -p "$1" || exit 70
ANCHOR_DIR="$(cd "$1" && pwd -P)"; shift          # sandbox subpath rules need the real path (/var -> /private/var)
WORK="$(mktemp -d /tmp/r3anc.XXXXXX)"; SOCK="$WORK/s"
PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m r3_shared.anchor_server --dir "$ANCHOR_DIR" --sock "$SOCK" >"$WORK/out" 2>"$WORK/err" &
APID=$!
for _ in $(seq 1 100); do grep -q '^READY' "$WORK/out" 2>/dev/null && break; kill -0 "$APID" 2>/dev/null || break; sleep 0.1; done
grep -q '^READY' "$WORK/out" || { echo "run_sandboxed: anchor failed to start: $(cat "$WORK/err")" >&2; kill "$APID" 2>/dev/null; exit 71; }
PROFILE="(version 1)(allow default)(deny file-write* (subpath \"$ANCHOR_DIR\"))"
R3_ANCHOR_SOCK="$SOCK" R3_ANCHOR_DIR="$ANCHOR_DIR" PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}" sandbox-exec -p "$PROFILE" "$@"
RC=$?
CLOSED="$(PYTHONPATH="$HERE/src" "$PY" -c "import json,sys; from r3_shared.anchor import close_anchor; print(json.dumps(close_anchor(sys.argv[1])['head']))" "$SOCK" 2>&1)"
echo "ANCHOR_CLOSED $CLOSED" >&2
wait "$APID" 2>/dev/null
rm -rf "$WORK"
exit $RC
