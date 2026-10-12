#!/usr/bin/env bash
# run_h29.sh --exp-id ID --variants a,b [--workers N] [--out-root D] [run_h29.py flags]      ONE launcher for dev, smoke and official runs.
# Per variant the launcher starts N independent SERVICE SETS (H27 anchor with control plane + ExternalWorld + AuthorityService, each its own OS
# process, started OUTSIDE the sandbox; one set per worker because every service has ONE tick), runs `run_h29.py run` under sandbox-exec
# (writes denied to every service directory) and under `caffeinate -dimsu`, closes ALL services (keys revealed, close() outputs recorded),
# moves their directories into the evidence dir (svc/) and runs `run_h29.py finalize` outside the sandbox. A trap kills every started server and
# removes the work dir; the script ends by asserting that no server of this run is left (ps check, G4 orphan lesson).
# Variants are INDEPENDENT (own work dir, own services) and run CONCURRENTLY; output is printed in variant order. R3_H29_SERIAL=1 runs them serially.
set -uo pipefail
R3="$(cd "$(dirname "$0")/.." && pwd -P)"; PY="${PY:-$R3/.venv/bin/python}"
ID=""; VARIANTS="paladin,conventional"; OUTROOT="$R3/experiments/h29"; WORKERS="${R3_H29_WORKERS:-4}"; PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --exp-id) ID="$2"; shift 2;; --variants) VARIANTS="$2"; shift 2;; --out-root) OUTROOT="$2"; shift 2;; --workers) WORKERS="$2"; shift 2;;
    *) PASS+=("$1"); shift;;
  esac
done
[ -n "$ID" ] || { echo "usage: run_h29.sh --exp-id ID [--variants a,b] [--workers N] [--out-root D] [run_h29.py flags]" >&2; exit 64; }
command -v sandbox-exec >/dev/null 2>&1 || { echo "run_h29: sandbox-exec unavailable - refusing to run unsandboxed" >&2; exit 69; }
export PYTHONPATH="$R3/src${PYTHONPATH:+:$PYTHONPATH}"
CAFF=""; command -v caffeinate >/dev/null 2>&1 && CAFF="caffeinate -dimsu"

run_one() {   # $1 = variant; own subshell: own WORK, own servers, own trap
  local V="$1" STATUS RC=0 W="$WORKERS"; WORK=""; PIDS=()   # trap vars stay global to the subshell: EXIT traps run after locals are gone
  cleanup() { for p in ${PIDS[@]+"${PIDS[@]}"}; do kill "$p" 2>/dev/null; done; [ -n "$WORK" ] && rm -rf "$WORK"; }
  trap cleanup EXIT
  WORK="$(mktemp -d /tmp/r3h29.XXXXXX)"; WORK="$(cd "$WORK" && pwd -P)"
  local OUT="$OUTROOT/$ID/${V##*:}" LOG="$WORK/run.log" i
  "$PY" -c "import json; from r3_harness.h28 import specs; print(json.dumps(specs.combined_systems()))" >"$WORK/systems.json" || return 70
  for i in $(seq 0 $((W-1))); do
    "$PY" -m r3_shared.anchor_server --dir "$WORK/anchor-$i" --sock "$WORK/anchor-$i.sock" --control >"$WORK/anchor-$i.out" 2>"$WORK/anchor-$i.err" & PIDS+=($!)
    "$PY" -m r3_shared.extworld_server --dir "$WORK/ext-$i" --systems "$WORK/systems.json" --socket "$WORK/ext-$i.sock" >"$WORK/ext-$i.out" 2>"$WORK/ext-$i.err" & PIDS+=($!)
    "$PY" -m r3_shared.authsvc_server --dir "$WORK/auth-$i" --socket "$WORK/auth-$i.sock" --lease 4 >"$WORK/auth-$i.out" 2>"$WORK/auth-$i.err" & PIDS+=($!)
  done
  for _ in $(seq 1 150); do
    local up=0; for i in $(seq 0 $((W-1))); do for s in anchor ext auth; do grep -q '^READY' "$WORK/$s-$i.out" 2>/dev/null && up=$((up+1)); done; done
    [ "$up" -eq $((3*W)) ] && break; sleep 0.1
  done
  [ "$up" -eq $((3*W)) ] || { echo "run_h29: service failed to start: $(cat "$WORK"/*.err 2>/dev/null | head -5)" >&2; return 71; }
  local PROFILE="(version 1)(allow default)(deny file-write*"; for i in $(seq 0 $((W-1))); do PROFILE="$PROFILE (subpath \"$WORK/anchor-$i\") (subpath \"$WORK/ext-$i\") (subpath \"$WORK/auth-$i\")"; done; PROFILE="$PROFILE)"
  R3_H29_SVC="$WORK" R3_H29_WORKERS="$W" $CAFF sandbox-exec -p "$PROFILE" "$PY" "$R3/scripts/run_h29.py" run --exp-id "$ID" --variant "$V" --out-root "$OUTROOT" ${PASS[@]+"${PASS[@]}"} >"$LOG.out" 2>"$LOG"
  STATUS=$?
  local CLOSES
  CLOSES="$(R3_H29_SVC="$WORK" R3_H29_WORKERS="$W" "$PY" - <<'PYEOF'
import json, os
from pathlib import Path
from r3_shared.anchor import close_anchor
from r3_shared.authsvc import AuthorityControl
from r3_shared.extworld import ExternalClient
root, W = Path(os.environ["R3_H29_SVC"]), int(os.environ["R3_H29_WORKERS"])
out = {"anchor": [], "ext": [], "auth": []}
for i in range(W):
    for key, fn in (("anchor", lambda: close_anchor(root / f"anchor-{i}.sock")), ("ext", lambda: ExternalClient(str(root / f"ext-{i}.sock"), str(root / f"ext-{i}.sock.ctl")).close()),
                    ("auth", lambda: AuthorityControl(str(root / f"auth-{i}.sock.ctl")).close())):
        try:
            out[key].append(fn())
        except Exception as exc:
            out[key].append({"error": str(exc)})
print(json.dumps(out))
PYEOF
)"
  for p in ${PIDS[@]+"${PIDS[@]}"}; do wait "$p" 2>/dev/null; done; PIDS=()
  cat "$LOG.out"; cat "$LOG" >&2
  if [ $STATUS -ne 0 ]; then echo "$V: run failed ($STATUS)" >&2; return $STATUS; fi
  mkdir -p "$OUT/svc" || return 72
  for i in $(seq 0 $((W-1))); do mv "$WORK/anchor-$i" "$WORK/ext-$i" "$WORK/auth-$i" "$OUT/svc/" || { echo "$V: cannot place service dirs" >&2; return 72; }; done
  $CAFF "$PY" "$R3/scripts/run_h29.py" finalize --exp-id "$ID" --variant "$V" --out-root "$OUTROOT" --closed "$CLOSES" ${PASS[@]+"${PASS[@]}"} || RC=1
  return $RC
}

RC=0; TMPO="$(mktemp -d /tmp/r3h29out.XXXXXX)"; PIDS=(); VS=()
trap 'for p in ${PIDS[@]+"${PIDS[@]}"}; do kill "$p" 2>/dev/null; done; rm -rf "$TMPO"' EXIT
for V in ${VARIANTS//,/ }; do
  VS+=("$V")
  ( run_one "$V" >"$TMPO/${V##*:}.out" 2>"$TMPO/${V##*:}.err"; echo $? >"$TMPO/${V##*:}.rc" ) & PIDS+=($!)
  [ "${R3_H29_SERIAL:-0}" = 1 ] && wait "$!" 2>/dev/null
done
for p in ${PIDS[@]+"${PIDS[@]}"}; do wait "$p" 2>/dev/null; done
for V in "${VS[@]}"; do
  cat "$TMPO/${V##*:}.out"; cat "$TMPO/${V##*:}.err" >&2
  R="$(cat "$TMPO/${V##*:}.rc" 2>/dev/null || echo 1)"; [ "$R" -ne 0 ] && RC=$R
done
LEAK="$(ps -eo pid,command | grep -E "r3_shared\.(anchor_server|extworld_server|authsvc_server|host)" | grep -v grep | grep -E "/tmp/r3h29\." || true)"
[ -n "$LEAK" ] && { echo "run_h29: LEAKED server processes of this run:" >&2; echo "$LEAK" >&2; RC=73; }
exit $RC
