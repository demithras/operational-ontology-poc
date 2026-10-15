#!/bin/bash
# Run the round3 suite as N parallel pytest processes (files balanced by measured duration).
# usage: scripts/run_tests_sharded.sh [N=8] [--refresh-durations] [--out DIR]
# Each shard: own pytest process, own TMPDIR (conftest also claims a private root), own --junitxml under DIR/shard-k/.
# Exit 0 only if every shard exits 0 and the merged junit has 0 failed / 0 errors.
set -u
ROUND3="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$ROUND3/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
N=8; REFRESH=0; OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --refresh-durations) REFRESH=1 ;;
    --out) shift; OUT="$1" ;;
    [0-9]*) N="$1" ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac; shift
done
[ -n "$OUT" ] || OUT="$(mktemp -d /tmp/r3shards.XXXXXX)"
mkdir -p "$OUT"; cd "$ROUND3" || exit 2
PLAN="$OUT/plan.txt"
"$PY" scripts/shard_tools.py plan "$N" > "$PLAN" || exit 2
START=$(date +%s)
pids=(); k=0
while IFS= read -r files; do
  d="$OUT/shard-$k"; mkdir -p "$d/tmp"; k=$((k+1))
  [ "$files" = "-" ] && continue
  echo "$files" | tr ' ' '\n' > "$d/files.txt"
  ( cd "$ROUND3" && R3_SHARD_FILES="$d/files.txt" TMPDIR="$d/tmp" "$PY" -m pytest -q -p no:cacheprovider --junitxml="$d/junit.xml" tests > "$d/log.txt" 2>&1; echo $? > "$d/exit" ) &
  pids+=($!)
done < "$PLAN"
wait "${pids[@]}"
echo "wall: $(( $(date +%s) - START ))s (N=$N, out=$OUT)"
rc=0
for d in "$OUT"/shard-*; do
  [ -f "$d/exit" ] || continue
  e=$(cat "$d/exit"); echo "$(basename "$d"): exit=$e | $(command grep -aE '[0-9]+ (passed|failed|error)' "$d/log.txt" | tail -1)"
  command grep -a "ANCHOR LEAK" "$d/log.txt" && rc=1
  [ "$e" = 0 ] || rc=1
done
xmls=("$OUT"/shard-*/junit.xml)
for x in "${xmls[@]}"; do [ -f "$x" ] || { echo "MISSING junit: $x" >&2; rc=1; }; done
[ "$REFRESH" = 1 ] && "$PY" scripts/shard_tools.py durations "${xmls[@]}"
"$PY" scripts/shard_tools.py merge "${xmls[@]}" || rc=1
exit $rc
