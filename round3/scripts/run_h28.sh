#!/usr/bin/env bash
# run_h28.sh --exp-id ID --variants a,b [--out-root D] [run_h28.py flags]      ONE launcher for dev, smoke and official runs.
# Per variant: the H27 anchor AND the ExternalWorld service are started OUTSIDE the sandbox (separate OS processes), run_h28.py `run`
# executes under sandbox-exec denying writes to both directories, both servers are closed (keys revealed), then `finalize` runs
# outside the sandbox. A trap closes/kills every started server and removes the work dir (no leaked processes).
set -uo pipefail
R3="$(cd "$(dirname "$0")/.." && pwd -P)"; PY="${PY:-$R3/.venv/bin/python}"
ID=""; VARIANTS="paladin,conventional"; OUTROOT="$R3/experiments/h28"; PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --exp-id) ID="$2"; shift 2;; --variants) VARIANTS="$2"; shift 2;; --out-root) OUTROOT="$2"; shift 2;;
    *) PASS+=("$1"); shift;;
  esac
done
[ -n "$ID" ] || { echo "usage: run_h28.sh --exp-id ID [--variants a,b] [--out-root D] [run_h28.py flags]" >&2; exit 64; }
command -v sandbox-exec >/dev/null 2>&1 || { echo "run_h28: sandbox-exec unavailable - refusing to run unsandboxed" >&2; exit 69; }
export PYTHONPATH="$R3/src${PYTHONPATH:+:$PYTHONPATH}"
WORK=""; APID=""; EPID=""
cleanup() {
  for p in $EPID $APID; do [ -n "$p" ] && kill "$p" 2>/dev/null; done
  [ -n "$WORK" ] && rm -rf "$WORK"
}
trap cleanup EXIT
RC=0
for V in ${VARIANTS//,/ }; do
  WORK="$(mktemp -d /tmp/r3h28.XXXXXX)"; WORK="$(cd "$WORK" && pwd -P)"; mkdir -p "$WORK/ext" "$WORK/anchor"
  OUT="$OUTROOT/$ID/$V"; LOG="$WORK/run.log"; APID=""; EPID=""
  "$PY" -c "import json; from r3_harness.h28 import specs; print(json.dumps(specs.combined_systems()))" >"$WORK/systems.json" || { RC=70; continue; }
  "$PY" -m r3_shared.anchor_server --dir "$WORK/anchor" --sock "$WORK/anchor.sock" >"$WORK/anchor.out" 2>"$WORK/anchor.err" & APID=$!
  "$PY" -m r3_shared.extworld_server --dir "$WORK/ext" --systems "$WORK/systems.json" --socket "$WORK/ext.sock" >"$WORK/ext.out" 2>"$WORK/ext.err" & EPID=$!
  for _ in $(seq 1 100); do grep -q '^READY' "$WORK/anchor.out" 2>/dev/null && grep -q '^READY' "$WORK/ext.out" 2>/dev/null && break; sleep 0.1; done
  if ! grep -q '^READY' "$WORK/anchor.out" || ! grep -q '^READY' "$WORK/ext.out"; then
    echo "run_h28: service failed to start: $(cat "$WORK/anchor.err" "$WORK/ext.err")" >&2; RC=71; cleanup; continue
  fi
  PROFILE="(version 1)(allow default)(deny file-write* (subpath \"$WORK/ext\") (subpath \"$WORK/anchor\"))"
  R3_EXT_SOCK="$WORK/ext.sock" R3_EXT_CTL="$WORK/ext.sock.ctl" R3_EXT_DIR="$WORK/ext" R3_ANCHOR_SOCK="$WORK/anchor.sock" R3_ANCHOR_DIR="$WORK/anchor" \
    sandbox-exec -p "$PROFILE" "$PY" "$R3/scripts/run_h28.py" run --exp-id "$ID" --variant "$V" --out-root "$OUTROOT" ${PASS[@]+"${PASS[@]}"} >"$LOG.out" 2>"$LOG"
  STATUS=$?
  EXTCLOSE="$("$PY" -c "import json,sys; from r3_shared.extworld import ExternalClient; print(json.dumps(ExternalClient(sys.argv[1], sys.argv[2]).close()))" "$WORK/ext.sock" "$WORK/ext.sock.ctl" 2>/dev/null)"
  ANCHORCLOSE="$("$PY" -c "import json,sys; from r3_shared.anchor import close_anchor; print(json.dumps(close_anchor(sys.argv[1])['head']))" "$WORK/anchor.sock" 2>/dev/null)"
  wait "$EPID" 2>/dev/null; wait "$APID" 2>/dev/null; EPID=""; APID=""
  cat "$LOG.out"; cat "$LOG" >&2
  if [ $STATUS -ne 0 ]; then echo "$V: run failed ($STATUS)" >&2; RC=$STATUS; rm -rf "$WORK"; WORK=""; continue; fi
  mkdir -p "$OUT" && mv "$WORK/ext" "$OUT/ext" && mv "$WORK/anchor" "$OUT/anchor" || { echo "$V: cannot place server dirs" >&2; RC=72; continue; }
  "$PY" "$R3/scripts/run_h28.py" finalize --exp-id "$ID" --variant "$V" --out-root "$OUTROOT" --closed-ext "$EXTCLOSE" --closed-anchor "$ANCHORCLOSE" \
    ${PASS[@]+"${PASS[@]}"} || RC=1
  rm -rf "$WORK"; WORK=""
done
exit $RC
