#!/usr/bin/env bash
# Re-hash the evidence of experiments/h28/<ID> (override root: R3_H28_OUT_ROOT), re-evaluate from the raw records + the closed ledger,
# and diff against the recorded verdict.json.
set -euo pipefail
ID="${1:?usage: verify_h28.sh <exp-id>}"; shift || true
R3="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PY:-$R3/.venv/bin/python}"
OUTROOT="${R3_H28_OUT_ROOT:-$R3/experiments/h28}"
EXP="$OUTROOT/$ID"
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
"$PY" "$R3/scripts/evaluate_h28.py" "$ID" --out-root "$OUTROOT" --print-only > "${TMPDIR:-/tmp}/h28-verify-$ID.json"
diff <("$PY" -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1])),indent=1,sort_keys=True))" "$EXP/verdict.json") \
     <("$PY" -c "import json,sys;print(json.dumps(json.load(open(sys.argv[1])),indent=1,sort_keys=True))" "${TMPDIR:-/tmp}/h28-verify-$ID.json") \
  && echo "verdict reproduces"
