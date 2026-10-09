#!/usr/bin/env bash
# run_h26.sh --exp-id ID --variants a,b [run_h26.py flags]   (ruling Q10: worlds get a HistoryStore + AnchorClient; the anchor
# service runs OUTSIDE the sandbox exactly as for H27). Per variant: anchor started by run_sandboxed.sh, run, anchor closed.
set -uo pipefail
R3="$(cd "$(dirname "$0")/.." && pwd -P)"; PY="${PY:-$R3/.venv/bin/python}"
ID=""; VARIANTS="paladin,conventional"; OUTROOT="$R3/experiments/h26"; PASS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --exp-id) ID="$2"; shift 2;; --variants) VARIANTS="$2"; shift 2;; --out-root) OUTROOT="$2"; shift 2;;
    *) PASS+=("$1"); shift;;
  esac
done
[ -n "$ID" ] || { echo "usage: run_h26.sh --exp-id ID [--variants a,b] [--out-root D] [run_h26.py flags]" >&2; exit 64; }
RC=0
for V in ${VARIANTS//,/ }; do
  AN="$OUTROOT/.anchors/$ID-$V"; mkdir -p "$AN"  # OUTSIDE the experiment dir (run_h26.py refuses an existing out dir; evaluate/verify scan it)
  "$R3/scripts/run_sandboxed.sh" "$AN" "$PY" "$R3/scripts/run_h26.py" --exp-id "$ID" --variants "$V" --out-root "$OUTROOT" ${PASS[@]+"${PASS[@]}"} || RC=$?
done
exit $RC
