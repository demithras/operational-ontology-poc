#!/usr/bin/env bash
# run_h28.sh --exp-id ID --variants a,b [--out-root D] [run_h28.py flags]      ONE launcher for dev, smoke and official runs.
# Per variant (G4-E26): the H27 anchor AND TWO ExternalWorld services (main: byz+controls; twin: the honest twins on the identical absolute
# clock schedule) are started OUTSIDE the sandbox (separate OS processes); run_h28.py `run` executes under sandbox-exec denying writes to
# all three directories; the servers are closed (keys revealed), then `finalize` runs outside the sandbox. A trap closes/kills every
# started server and removes the work dir (no leaked processes).
# The variants are INDEPENDENT (own work dir, own anchor, own ExternalWorlds) and run CONCURRENTLY; their output is printed in variant order
# after all finish. R3_H28_SERIAL=1 runs them one after the other (same evidence bytes; only wall time differs).
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

run_one() {   # $1 = variant; runs in its own subshell: own WORK, own servers, own trap
  local V="$1" STATUS RC=0; WORK=""; APID=""; EPID=""; TPID=""   # trap vars stay global to the subshell: EXIT traps run after locals are gone
  cleanup() { for p in $TPID $EPID $APID; do [ -n "$p" ] && kill "$p" 2>/dev/null; done; [ -n "$WORK" ] && rm -rf "$WORK"; }
  trap cleanup EXIT
  WORK="$(mktemp -d /tmp/r3h28.XXXXXX)"; WORK="$(cd "$WORK" && pwd -P)"; mkdir -p "$WORK/ext" "$WORK/ext-twin" "$WORK/anchor"
  local OUT="$OUTROOT/$ID/$V" LOG="$WORK/run.log"
  "$PY" -c "import json; from r3_harness.h28 import specs; print(json.dumps(specs.combined_systems()))" >"$WORK/systems.json" || return 70
  "$PY" -m r3_shared.anchor_server --dir "$WORK/anchor" --sock "$WORK/anchor.sock" >"$WORK/anchor.out" 2>"$WORK/anchor.err" & APID=$!
  "$PY" -m r3_shared.extworld_server --dir "$WORK/ext" --systems "$WORK/systems.json" --socket "$WORK/ext.sock" >"$WORK/ext.out" 2>"$WORK/ext.err" & EPID=$!
  "$PY" -m r3_shared.extworld_server --dir "$WORK/ext-twin" --systems "$WORK/systems.json" --socket "$WORK/twin.sock" >"$WORK/twin.out" 2>"$WORK/twin.err" & TPID=$!
  for _ in $(seq 1 100); do grep -q '^READY' "$WORK/anchor.out" 2>/dev/null && grep -q '^READY' "$WORK/ext.out" 2>/dev/null && grep -q '^READY' "$WORK/twin.out" 2>/dev/null && break; sleep 0.1; done
  if ! grep -q '^READY' "$WORK/anchor.out" || ! grep -q '^READY' "$WORK/ext.out" || ! grep -q '^READY' "$WORK/twin.out"; then
    echo "run_h28: service failed to start: $(cat "$WORK/anchor.err" "$WORK/ext.err" "$WORK/twin.err")" >&2; return 71
  fi
  local PROFILE="(version 1)(allow default)(deny file-write* (subpath \"$WORK/ext\") (subpath \"$WORK/ext-twin\") (subpath \"$WORK/anchor\"))"
  R3_EXT_SOCK="$WORK/ext.sock" R3_EXT_CTL="$WORK/ext.sock.ctl" R3_EXT_DIR="$WORK/ext" \
  R3_EXT_TWIN_SOCK="$WORK/twin.sock" R3_EXT_TWIN_CTL="$WORK/twin.sock.ctl" R3_EXT_TWIN_DIR="$WORK/ext-twin" \
  R3_ANCHOR_SOCK="$WORK/anchor.sock" R3_ANCHOR_DIR="$WORK/anchor" \
    sandbox-exec -p "$PROFILE" "$PY" "$R3/scripts/run_h28.py" run --exp-id "$ID" --variant "$V" --out-root "$OUTROOT" ${PASS[@]+"${PASS[@]}"} >"$LOG.out" 2>"$LOG"
  STATUS=$?
  local close='import json,sys; from r3_shared.extworld import ExternalClient; print(json.dumps(ExternalClient(sys.argv[1], sys.argv[2]).close()))'
  local EXTCLOSE TWINCLOSE ANCHORCLOSE
  EXTCLOSE="$("$PY" -c "$close" "$WORK/ext.sock" "$WORK/ext.sock.ctl" 2>/dev/null)"
  TWINCLOSE="$("$PY" -c "$close" "$WORK/twin.sock" "$WORK/twin.sock.ctl" 2>/dev/null)"
  ANCHORCLOSE="$("$PY" -c "import json,sys; from r3_shared.anchor import close_anchor; print(json.dumps(close_anchor(sys.argv[1])['head']))" "$WORK/anchor.sock" 2>/dev/null)"
  wait "$TPID" 2>/dev/null; wait "$EPID" 2>/dev/null; wait "$APID" 2>/dev/null; TPID=""; EPID=""; APID=""
  cat "$LOG.out"; cat "$LOG" >&2
  if [ $STATUS -ne 0 ]; then echo "$V: run failed ($STATUS)" >&2; return $STATUS; fi
  mkdir -p "$OUT" && mv "$WORK/ext" "$OUT/ext" && mv "$WORK/ext-twin" "$OUT/ext-twin" && mv "$WORK/anchor" "$OUT/anchor" || { echo "$V: cannot place server dirs" >&2; return 72; }
  "$PY" "$R3/scripts/run_h28.py" finalize --exp-id "$ID" --variant "$V" --out-root "$OUTROOT" --closed-ext "$EXTCLOSE" --closed-ext-twin "$TWINCLOSE" \
    --closed-anchor "$ANCHORCLOSE" ${PASS[@]+"${PASS[@]}"} || RC=1
  return $RC
}

RC=0; TMPO="$(mktemp -d /tmp/r3h28out.XXXXXX)"; PIDS=(); VS=()
trap 'for p in ${PIDS[@]+"${PIDS[@]}"}; do kill "$p" 2>/dev/null; done; rm -rf "$TMPO"' EXIT
for V in ${VARIANTS//,/ }; do
  VS+=("$V")
  ( run_one "$V" >"$TMPO/$V.out" 2>"$TMPO/$V.err"; echo $? >"$TMPO/$V.rc" ) & PIDS+=($!)
  [ "${R3_H28_SERIAL:-0}" = 1 ] && wait "$!" 2>/dev/null
done
for p in ${PIDS[@]+"${PIDS[@]}"}; do wait "$p" 2>/dev/null; done
for V in "${VS[@]}"; do
  cat "$TMPO/$V.out"; cat "$TMPO/$V.err" >&2
  R="$(cat "$TMPO/$V.rc" 2>/dev/null || echo 1)"; [ "$R" -ne 0 ] && RC=$R
done
exit $RC
