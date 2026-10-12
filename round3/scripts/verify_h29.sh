#!/usr/bin/env bash
# Re-hash the evidence of experiments/h29/<ID> (override root: R3_H29_OUT_ROOT), re-evaluate from the raw records + the closed ledger,
# and diff against the recorded verdict.json.
set -euo pipefail
# usage: verify_h29.sh <exp-id | path-to-experiment-dir>
#   an id is resolved under $R3_H29_OUT_ROOT (default experiments/h29); anything containing a '/' is taken as the experiment directory itself.
case "${1:-}" in -h|--help) sed -n 2,6p "$0"; exit 0;; esac
ARG="${1:?usage: verify_h29.sh <exp-id | path-to-experiment-dir>}"; shift || true
R3="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$R3/.venv/bin/python}"
OUTROOT="${R3_H29_OUT_ROOT:-$R3/experiments/h29}"
if [[ "$ARG" == */* ]]; then EXP="$(cd "$ARG" 2>/dev/null && pwd -P)" || { echo "no such experiment directory: $ARG" >&2; exit 2; }; OUTROOT="$(dirname "$EXP")"; ID="$(basename "$EXP")"
else ID="$ARG"; EXP="$OUTROOT/$ID"; fi
[ -f "$EXP/verdict.json" ] || { echo "no verdict.json in $EXP" >&2; exit 2; }
"$PY" - "$EXP" <<'PYEOF'
import hashlib, json, pathlib, sys
exp = pathlib.Path(sys.argv[1]); bad = 0
for v in sorted(p for p in exp.iterdir() if p.is_dir()):
    man = json.loads((v / "manifest.json").read_text())
    for f, h in man["raw_observations"]["evidence_sha256"].items():
        if hashlib.sha256((v / f).read_bytes()).hexdigest() != h:
            print(f"HASH MISMATCH {v.name}/{f}"); bad += 1
if bad: sys.exit(1)
print("evidence hashes ok")
PYEOF
"$PY" - "$EXP" "$ID" <<'PYEOF'
import json, pathlib, sys
exp, eid = pathlib.Path(sys.argv[1]), sys.argv[2]
for v in sorted(p for p in exp.iterdir() if p.is_dir()):
    ov = json.loads((v / "manifest.json").read_text())["raw_observations"].get("dev_overrides")
    if ov and "-dev" not in eid:
        print(f"FROZEN MINIMUM OVERRIDDEN in non-dev experiment {eid}: {v.name} {ov}"); sys.exit(1)
PYEOF
"$PY" "$R3/scripts/evaluate_h29.py" "$ID" --out-root "$OUTROOT" --print-only > "${TMPDIR:-/tmp}/h29-verify-$ID.json"
diff <("$PY" -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1])),indent=1,sort_keys=True))" "$EXP/verdict.json") \
     <("$PY" -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1])),indent=1,sort_keys=True))" "${TMPDIR:-/tmp}/h29-verify-$ID.json") \
  && echo "verdict reproduces"
