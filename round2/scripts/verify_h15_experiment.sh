#!/usr/bin/env bash
# H15 Phase 3 acceptance checks. One line per check: "PASS <name>: <evidence>" or "FAIL <name>: <evidence>".
# Exit status 1 if any FAIL. EXP selects the experiment directory (default exp-h15-001). Run from anywhere.
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
PY="$R2/.venv/bin/python"
EXP="${EXP:-exp-h15-001}"
EDIR="$R2/experiments/h15/$EXP"
FAILS=0
report() { # name, exit-code, evidence
  if [ "$2" -eq 0 ]; then echo "PASS $1: $3"; else echo "FAIL $1: $3"; FAILS=$((FAILS+1)); fi
}
cd "$R2" || exit 1

out=$("$PY" scripts/h15_gate0_hash.py --check 2>&1); rc=$?
report gate0_check $rc "$(echo "$out" | tail -1)"

out=$("$PY" - <<'PY' 2>&1
import hashlib, json, pathlib, subprocess
root = pathlib.Path(".")
fz = json.loads((root / "protocol/FREEZE.json").read_text())
bad = [f["path"] for f in fz["files"] if hashlib.sha256((root / f["path"]).read_bytes()).hexdigest() != f["sha256"]]
g0 = [f["path"] for f in json.loads((root / "protocol/H15_GATE0.json").read_text())["files"]]
cand = [f["path"] for f in json.loads((root / "protocol/H15_CANDIDATE.json").read_text())["files"]]
paths = ["protocol/FREEZE.json", "protocol/H15_GATE0.json", "protocol/H15_CANDIDATE.json"] + [f["path"] for f in fz["files"]] + g0 + cand
diff = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", *paths], capture_output=True, text=True).stdout.split()
print(f"{len(fz['files'])} frozen hashes match={not bad} {bad}; git diff vs HEAD on {len(paths)} frozen/gate0/candidate paths: {diff or 'none'}")
raise SystemExit(1 if bad or diff else 0)
PY
); rc=$?
report freeze_and_candidate_files_unchanged $rc "$out"

out=$("$PY" - <<'PY' 2>&1
import sys
sys.path.insert(0, "src")
from eoo_h15 import evidence
pre = evidence.preflight()
print(f"freeze {pre['protocol_freeze_hash'][:12]}.. gate0 {pre['gate0_combined_sha256'][:12]}.. candidate {pre['candidate_combined_sha256'][:12]}.. "
      f"openpona {pre['openpona_installed']['commit'][:7]} tokens/grammar hashes equal the contract pin")
PY
); rc=$?
report preflight_recomputed $rc "$out"

out=$("$PY" -m pytest -q -p no:cacheprovider tests/h15/test_evaluate_h15.py 2>&1); rc=$?
report evaluator_tests $rc "$(echo "$out" | grep -E '[0-9]+ (passed|failed)' | tail -1)"

out=$("$PY" - "$EDIR" <<'PY' 2>&1
import hashlib, json, pathlib, subprocess, sys
import jsonschema
sys.path.insert(0, "src")
from eoo_h15.evidence import REQUIRED, freeze_hash
from eoo_h15.util import canon, sha_text
d = pathlib.Path(sys.argv[1])
schema = json.loads(pathlib.Path("schemas/evidence-record.schema.json").read_text())
fz = json.loads(pathlib.Path("protocol/FREEZE.json").read_text())["protocol_sha256"]
bad, info = [], []
recs = {}
for f in REQUIRED:
    p = d / f
    if not p.is_file():
        bad.append(f"{f} missing")
        continue
    r = json.loads(p.read_text())
    recs[f] = r
    try:
        jsonschema.validate(r, schema)
    except jsonschema.ValidationError as e:
        bad.append(f"{f} schema: {e.message[:80]}")
    if sha_text(canon(r["payload"])) != r["payload_hash"]:
        bad.append(f"{f} payload_hash")
    if r["protocol_freeze_hash"] != fz:
        bad.append(f"{f} freeze hash")
    for k in ("git_commit", "seed", "input_corpus_hash", "oracle_version", "environment", "gate0_combined_sha256", "candidate_combined_sha256", "openpona_pin", "harness_sha256"):
        if r.get(k) in (None, "", {}):
            bad.append(f"{f} lacks {k}")
ids = {(r["git_commit"], r["seed"], r["input_corpus_hash"], r["experiment_id"]) for r in recs.values()}
if len(ids) > 1:
    bad.append(f"records disagree on provenance: {ids}")
if recs:
    r0 = next(iter(recs.values()))
    cur = {k: hashlib.sha256(pathlib.Path(k).read_bytes()).hexdigest() for k in r0["harness_sha256"]}
    changed = [k for k, v in r0["harness_sha256"].items() if cur.get(k) != v]
    if changed:
        bad.append(f"harness files changed since the run: {changed}")
    info.append(f"commit {r0['git_commit'][:7]} seed {r0['seed']} harness_dirty={r0['harness_dirty']} "
                f"run_h15.py={r0['harness_sha256'].get('scripts/run_h15.py','?')[:10]} evaluate_h15.py={r0['harness_sha256'].get('scripts/evaluate_h15.py','?')[:10]}")
print(f"{len(recs)}/6 evidence files schema-valid, payload hashes match, freeze hash equal; " + "; ".join(info) + (f"; PROBLEMS {bad}" if bad else ""))
raise SystemExit(1 if bad or len(recs) != 6 else 0)
PY
); rc=$?
report evidence_present_schema_valid $rc "$out"

out=$("$PY" - "$EDIR" <<'PY' 2>&1
import json, pathlib, sys
d = pathlib.Path(sys.argv[1])
g = json.loads((d / "generated-roundtrip.json").read_text())["payload"]
op, dsl = g["surfaces"]["openpona"], g["surfaces"]["dsl"]
ok = g["valid_cases"] >= 10000 and op["ok"] == g["valid_cases"] and op["failed"] == 0 and op["unrepresentable"] == 0 \
     and g["generation"]["invalid_under_validate"] == 0
print(f"generated valid={g['valid_cases']} (unique {g['generation']['unique']}); openpona ok/failed/unrepresentable={op['ok']}/{op['failed']}/{op['unrepresentable']} "
      f"exact={op['exact_equal']}; dsl baseline ok/failed={dsl['ok']}/{dsl['failed']}; corpus {g['generation']['corpus_sha256'][:12]}..")
raise SystemExit(0 if ok else 1)
PY
); rc=$?
report generated_valid_ge_10000_zero_failures $rc "$out"

out=$("$PY" - "$EDIR" <<'PY' 2>&1
import json, pathlib, sys
d = pathlib.Path(sys.argv[1])
def P(f): return json.loads((d / f).read_text())["payload"]
real, side, amb, mut, met = P("real-domain-roundtrip.json"), P("sidecar-audit.json"), P("ambiguity-corpus.json"), P("mutation-results.json"), P("compiler-diff-metrics.json")
msgs, bad = [], 0
for k, v in real.items():
    msgs.append(f"{k}: {v['resources_total']} resources equivalent={v['openpona']['equivalent']} complete={v['openpona']['encoded_completely']}")
    bad += not (v["openpona"]["equivalent"] and v["openpona"]["encoded_completely"])
a = amb["summary"]["openpona"]
msgs.append(f"ambiguity declared {a['declared_fail_closed']}/{a['declared_total']} fail closed, deletion mutants {a['deletion_total']} violations={a['deletion_violations']}")
bad += not (a["declared_fail_closed"] == a["declared_total"] and a["deletion_violations"] == 0 and a["deletion_total"] >= 1000)
msgs.append(f"sidecar indispensable={side['indispensable_sidecar_count']} vocab_violations={side['record_vocabulary_violations']}")
bad += side["indispensable_sidecar_count"] != 0
msgs.append(f"new primitive tokens={met['primitive_tokens']['new_primitive_tokens_required']} gaps={met['gap_constructs']['count']}")
bad += met["primitive_tokens"]["new_primitive_tokens_required"] != 0
msgs.append("mutation " + ", ".join(f"{s} {x['killed']}/{x['target_mutants']}" for s, x in mut["summary"].items())
            + f"; controls clean {[c['clean'] and c['clean_after_restore'] for c in mut['controls'].values()]}; survivors(extra,info) "
            + str([m['id'] for m in mut['mutants'] if not m['killed']]))
bad += not all(x["killed"] == x["target_mutants"] == 6 for x in mut["summary"].values())
print("; ".join(msgs))
raise SystemExit(1 if bad else 0)
PY
); rc=$?
report evidence_content_checks $rc "$out"

T="${TMPDIR:-/tmp}/verify_h15_exp.$$"; mkdir -p "$T"
out=$("$PY" - "$EDIR" "$T" <<'PY' 2>&1
import json, pathlib, shutil, sys
sys.path.insert(0, "src")
from eoo_h15.evaluate import evaluate
from eoo_h15.report import render_report
d, tmp = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
v = evaluate(d)
saved = json.loads((d / "verdict.json").read_text())
same = json.dumps(v, sort_keys=True) == json.dumps(saved, sort_keys=True)
rep = (d / "REPORT.md").read_text() == render_report(d, v)
# known negative: a tampered copy of the evidence must not reproduce the verdict
c = tmp / "copy"
shutil.copytree(d, c)
r = json.loads((c / "generated-roundtrip.json").read_text())
r["payload"]["surfaces"]["openpona"]["failed"] = 1
(c / "generated-roundtrip.json").write_text(json.dumps(r))
vt = evaluate(c)
neg = vt["verdict"] != v["verdict"] or v["verdict"] != "SUPPORTED"
print(f"verdict {v['verdict']} recomputed identical={same}; REPORT.md regenerated identical={rep}; tampered copy -> {vt['verdict']} (problems {len(vt['problems'])})")
raise SystemExit(0 if same and rep and neg and vt["verdict"] != "SUPPORTED" else 1)
PY
); rc=$?
rm -rf "$T"
report verdict_recomputes_identically $rc "$out"

out=$(PATH="$R2/.venv/bin:$PATH" make -s check 2>&1); rc=$?
echo "$out" | grep -q "PACK OK" || rc=1
report make_check $rc "$(echo "$out" | tail -1)"

if [ "${VERIFY_SKIP_PYTEST:-0}" = "1" ]; then  # quick known-negative runs only: a skip is never a PASS
  report pytest_full_round2 1 "skipped (VERIFY_SKIP_PYTEST=1)"
else
  LOG="${TMPDIR:-/tmp}/verify_h15_experiment_pytest.$$.log"
  "$PY" -m pytest -q -p no:cacheprovider > "$LOG" 2>&1; rc=$?
  summary=$(grep -E "[0-9]+ (passed|failed).* in [0-9.]+s" "$LOG" | tail -1)
  failed=$(grep -E "^(FAILED|ERROR) " "$LOG" | head -5 | tr '\n' ';')
  report pytest_full_round2 $rc "${summary:-no summary line} ${failed}"
  rm -f "$LOG"
fi

echo "verify_h15_experiment: $FAILS FAIL(s)"
[ "$FAILS" -eq 0 ]
