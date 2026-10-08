#!/usr/bin/env bash
# Re-hash the evidence of experiments/h26/<ID> (override root: R3_H26_OUT_ROOT), re-evaluate, and diff against the recorded verdict.json.
set -euo pipefail
ID="${1:?usage: verify_h26.sh <exp-id> [extra evaluate args]}"; shift || true
R3="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$R3/.venv/bin/python}"
OUTROOT="${R3_H26_OUT_ROOT:-$R3/experiments/h26}"
EXP="$OUTROOT/$ID"
[ -f "$EXP/verdict.json" ] || { echo "no verdict.json in $EXP" >&2; exit 2; }
"$PY" - "$EXP" <<'PYEOF'
import hashlib, json, pathlib, sys
exp = pathlib.Path(sys.argv[1]); bad = 0
for v in sorted(p for p in exp.iterdir() if p.is_dir()):
    env = json.loads((v / "envelope.json").read_text())
    for f, h in env["raw_observations"]["evidence_sha256"].items():
        got = hashlib.sha256((v / f).read_bytes()).hexdigest()
        if got != h:
            print(f"HASH MISMATCH {v.name}/{f}"); bad += 1
if bad: sys.exit(1)
print("evidence hashes ok")
PYEOF
"$PY" - "$EXP" "$ID" <<'PYEOF'
import json, sys
v = json.load(open(sys.argv[1] + "/verdict.json")); ov = v.get("minimum_overrides")
if ov and "-dev" not in sys.argv[2]:
    print(f"FROZEN MINIMUM OVERRIDDEN in non-dev experiment {sys.argv[2]}: {ov}"); sys.exit(1)
PYEOF
"$PY" "$R3/scripts/evaluate_h26.py" "$ID" --out-root "$OUTROOT" --print-only "$@" > "${TMPDIR:-/tmp}/h26-verify-$ID.json"
diff <("$PY" -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1])),indent=1,sort_keys=True))" "$EXP/verdict.json") \
     <("$PY" -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1])),indent=1,sort_keys=True))" "${TMPDIR:-/tmp}/h26-verify-$ID.json") \
  && echo "verdict reproduces"
