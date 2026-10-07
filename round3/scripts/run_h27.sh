#!/usr/bin/env bash
# run_h27.sh --exp-id ID --variants a,b [--seed N] [other run_h27.py flags]   (PROT-H27 s4: sandboxed anchor per variant)
# Per variant: anchor started OUTSIDE the sandbox, the run under sandbox-exec denying writes to <exp>/<variant>/anchor,
# then the anchor is closed (key revealed) and the audit/envelope are finalized outside the sandbox.
set -uo pipefail
R3="$(cd "$(dirname "$0")/.." && pwd -P)"; PY="${PY:-$R3/.venv/bin/python}"
ID=""; VARIANTS="paladin,conventional"; OUTROOT="$R3/experiments/h27"; PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --exp-id) ID="$2"; shift 2;; --variants) VARIANTS="$2"; shift 2;; --out-root) OUTROOT="$2"; shift 2;;
    *) PASS+=("$1"); shift;;
  esac
done
[ -n "$ID" ] || { echo "usage: run_h27.sh --exp-id ID [--variants a,b] [--out-root D] [run_h27.py flags]" >&2; exit 64; }
RC=0
for V in ${VARIANTS//,/ }; do
  OUT="$OUTROOT/$ID/$V"; mkdir -p "$OUT"; LOG="$OUT/run.log"
  "$R3/scripts/run_sandboxed.sh" "$OUT/anchor" "$PY" "$R3/scripts/run_h27.py" run --exp-id "$ID" --variant "$V" --out-root "$OUTROOT" ${PASS[@]+"${PASS[@]}"} >"$LOG.out" 2>"$LOG"
  STATUS=$?
  cat "$LOG.out"; grep -v '^ANCHOR_CLOSED' "$LOG" >&2 || true
  if [ $STATUS -ne 0 ]; then echo "$V: run failed ($STATUS)" >&2; RC=$STATUS; continue; fi
  HEAD="$(grep '^ANCHOR_CLOSED ' "$LOG" | tail -1 | sed -E 's/^ANCHOR_CLOSED //')"
  FIN=(); for x in ${PASS[@]+"${PASS[@]}"}; do [ "$x" = "--test-variants" ] && FIN+=(--test-variants); done
  "$PY" "$R3/scripts/run_h27.py" finalize --exp-id "$ID" --variant "$V" --out-root "$OUTROOT" --closed-head "$HEAD" ${FIN[@]+"${FIN[@]}"} || RC=1
done
exit $RC
