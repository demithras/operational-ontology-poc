#!/usr/bin/env bash
# Re-runs every acceptance check of P12 (H18w: project contract v3 + weak-H18 evaluator). One line per check: PASS/FAIL <name>: <evidence>.
# Exits non-zero on any FAIL. Read-only git only (diff / status / rev-parse). Usage: scripts/verify_h18w.sh [<dev-run-evidence-dir>]
cd "$(dirname "$0")/.." || exit 2
R=$(pwd); PY="$R/.venv/bin/python"; FAILS=0
TMP=$(mktemp -d "${TMPDIR:-/tmp}/verify-h18w.XXXXXX")
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS+1)); }
tail1() { tail -n 1 "$1" | tr -d '\r'; }
pyt() {  # name, log, pytest args... : passes when pytest exits 0 and its summary has no failed/error
  local name=$1 log=$2; shift 2
  "$PY" -m pytest -q -p no:cacheprovider "$@" > "$log" 2>&1; local rc=$?
  local sum; sum=$(grep -E '^[0-9]+ (passed|failed)|[0-9]+ (passed|failed|error)' "$log" | tail -n 1)
  if [ $rc -eq 0 ] && ! grep -qE '[0-9]+ (failed|error)' "$log"; then pass "$name" "$sum"; else fail "$name" "rc=$rc $sum (see $log)"; fi
}

# 1. counterexample classes: red on v2, green on v3
pyt v2_red_counterexamples "$TMP/red.log" tests/h18/test_v3_h18.py -k "RED or oracle_illegal_class"
pyt v3_green_counterexamples "$TMP/green.log" tests/h18/test_v3_h18.py -k "GREEN or still or is_v2_plus or byte_identical or selectable"
# 2. evaluator: one known-positive + one known-negative per clause (S1,S1b,S2,S3,S4,S6,R,I,V1-V6)
pyt evaluator_tests_h18w "$TMP/eval.log" tests/h18/test_evaluate_h18w.py
miss=""
for c in S1 S1b S2 S3 S4 S6 R I V1 V2 V3 V4 V5 V6; do grep -qE "test_${c}_" tests/h18/test_evaluate_h18w.py || miss="$miss $c"; done
[ -z "$miss" ] && pass evaluator_clause_coverage "a named negative test for each of S1 S1b S2 S3 S6 R I V1..V6" || fail evaluator_clause_coverage "no test_<clause>_ for:$miss"
# 3. Engine and oracle unchanged vs tag r2-engine-v1.2 (tracked diff + untracked files)
if git rev-parse --verify --quiet 'r2-engine-v1.2^{commit}' > /dev/null; then
  d=$(git diff --name-only r2-engine-v1.2 -- src/eoo_engine src/eoo_engine_git; git status --porcelain --untracked-files=all -- src/eoo_engine src/eoo_engine_git)
  [ -z "$d" ] && pass engine_unchanged_vs_r2-engine-v1.2 "no diff, no untracked in src/eoo_engine, src/eoo_engine_git" || fail engine_unchanged_vs_r2-engine-v1.2 "$d"
  d=$(git diff --name-only r2-engine-v1.2 -- src/hdd/project_lifecycle_reference.py oracles/h18; git status --porcelain --untracked-files=all -- src/hdd/project_lifecycle_reference.py oracles/h18)
  [ -z "$d" ] && pass oracle_unchanged_vs_r2-engine-v1.2 "no diff in src/hdd/project_lifecycle_reference.py, oracles/h18" || fail oracle_unchanged_vs_r2-engine-v1.2 "$d"
else fail engine_unchanged_vs_r2-engine-v1.2 "tag r2-engine-v1.2 not found"; fi
# 4. frozen / read-only trees and the older contracts unchanged vs HEAD
d=$(git diff --name-only HEAD -- protocol hypotheses experiments domains/project/ir.json domains/project/ir.v2.json ontology schemas src/eoo_ir src/eoo_dsl src/eoo_openpona src/hdd)
[ -z "$d" ] && pass frozen_and_ir_v1_v2_unchanged_vs_HEAD "protocol hypotheses experiments ir.json ir.v2.json src/hdd unchanged" || fail frozen_and_ir_v1_v2_unchanged_vs_HEAD "$d"
d=$(git diff --name-only r2-engine-v1.2 -- domains/project/ir.json domains/project/ir.v2.json)
[ -z "$d" ] && pass ir_v2_byte_identical_vs_tag "ir.json, ir.v2.json equal to r2-engine-v1.2" || fail ir_v2_byte_identical_vs_tag "$d"
# 5. v3 is v2 + exactly the two declared changes, with CHANGES_v3.md carrying the diff
"$PY" - > "$TMP/ir.out" 2>&1 <<'PYEOF'
import json, sys
v2 = json.load(open("domains/project/ir.v2.json")); v3 = json.load(open("domains/project/ir.v3.json"))
ids = lambda ir, k: [x["id"] for x in ir[k]]
assert v3["version"] == "v3" and v2["version"] == "v2"
assert ids(v3, "link_types") == ids(v2, "link_types") + ["NEW_VERSION_OF"], "link types"
for k in ("object_types", "functions", "policies", "authority_rules", "observation_types", "constraints"):
    assert v3[k] == v2[k], k
chg = [a["id"] for a, b in zip(v3["actions"], v2["actions"]) if a != b]
assert chg == ["new_experiment_version", "supersede_hypothesis"], chg
sup = next(a for a in v3["actions"] if a["id"] == "supersede_hypothesis")
assert sup["policy_refs"][-1] == "policy:conflicting_change_denied_with_conflict"
nv = next(a for a in v3["actions"] if a["id"] == "new_experiment_version")
assert nv["effects"][-1] == {"target": "NEW_VERSION_OF", "operation": "git_change"} and len(nv["effects"]) == 3
md = open("domains/project/CHANGES_v3.md").read()
assert "## JSON diff v2 -> v3" in md and '+          "target": "NEW_VERSION_OF"' in md and '+  "version": "v3"' in md, "CHANGES_v3.md lacks the JSON diff"
print("changed actions", chg, "| new link NEW_VERSION_OF | CHANGES_v3.md has the JSON diff")
PYEOF
[ $? -eq 0 ] && pass ir_v3_is_v2_plus_two_changes "$(tail1 "$TMP/ir.out")" || fail ir_v3_is_v2_plus_two_changes "$(tail -n 3 "$TMP/ir.out" | tr '\n' ' ')"
# 6. defaults: pack/_pack default v3 (v1, v2 selectable); run_h18.py default stays v2
"$PY" - > "$TMP/def.out" 2>&1 <<'PYEOF'
import sys, re
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from domains._pack import load_ir
from domains.project.pack import build_pack
assert load_ir("project")["version"] == "v3"
for v in ("v1", "v2", "v3"):
    assert load_ir("project", v)["version"] == v; build_pack(ir_version=v)
s = open("scripts/run_h18.py").read()
assert re.search(r'--ir-version", default="v2"', s), "run_h18.py default must stay v2"
print("pack/_pack default v3; v1 v2 v3 selectable; run_h18.py --ir-version default v2")
PYEOF
[ $? -eq 0 ] && pass defaults "$(tail1 "$TMP/def.out")" || fail defaults "$(tail -n 3 "$TMP/def.out" | tr '\n' ' ')"
# 7. dry runs: tiny real run on v3 and on v2 (records the ir version), evaluated by evaluate_h18w (writes nothing)
for v in v3 v2; do
  "$PY" scripts/run_h18.py --exp-id dry-$v --seed 1818 --n 30 --mutation-cases 12 --ir-version $v --out-root "$TMP/dry" > "$TMP/dry-$v.log" 2>&1; rc=$?
  "$PY" scripts/evaluate_h18w.py "$TMP/dry/dry-$v" --no-write > "$TMP/dry-$v.eval" 2>&1; erc=$?
  got=$("$PY" -c "import json,sys;print(json.load(open('$TMP/dry/dry-$v/project-state-machine.json')).get('ir_version'))" 2>/dev/null)
  hyp=$(grep -o '"hypothesis_id": "[^"]*"' "$TMP/dry-$v.eval" | head -n 1); ver=$(grep -o '"verdict": "[^"]*"' "$TMP/dry-$v.eval" | head -n 1)
  if [ $rc -eq 0 ] && [ $erc -eq 0 ] && [ "$got" = "$v" ] && [ "$hyp" = '"hypothesis_id": "H18w"' ]; then pass dry_run_ir_$v "run rc=0, record ir_version=$got, evaluate_h18w $ver (30 cases: INCONCLUSIVE/INVALID expected)"; else fail dry_run_ir_$v "rc=$rc erc=$erc ir_version=$got $hyp $(tail -n 2 "$TMP/dry-$v.log" | tr '\n' ' ')"; fi
done
# 8. optional: a dev-run evidence dir passed as $1 is re-evaluated read-only and its per-class counts are printed
if [ -n "$1" ]; then
  "$PY" scripts/evaluate_h18w.py "$1" --no-write > "$TMP/dev.eval" 2>&1
  "$PY" - "$1" > "$TMP/dev.out" 2>&1 <<'PYEOF'
import json, sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from eoo_h18.evaluate_w import evaluate
v = evaluate(sys.argv[1]); n = v["numbers"]
print(f"verdict={v['verdict']} unique={n['unique_cases']} steps={n['steps']} illegal_accepted_by_class={n['illegal_accepted_by_class']} legal_rejected_by_class={n['legal_rejected_by_class']} ir={n['ir_version_in_evidence']}")
PYEOF
  [ $? -eq 0 ] && pass dev_run_reevaluated "$(tail1 "$TMP/dev.out")" || fail dev_run_reevaluated "$(tail -n 3 "$TMP/dev.out" | tr '\n' ' ')"
fi
# 9. suites
pyt tests_h18_and_domains "$TMP/h18dom.log" tests/h18 tests/domains
pyt full_round2_suite "$TMP/full.log" tests
if "$PY" scripts/check_pack.py > "$TMP/make.log" 2>&1 && grep -q "PACK OK" "$TMP/make.log"; then pass make_check "$(grep -m1 'PACK OK' "$TMP/make.log")"; else fail make_check "$(tail -n 3 "$TMP/make.log" | tr '\n' ' ')"; fi
echo "logs: $TMP"
[ $FAILS -eq 0 ] && echo "ALL CHECKS PASS" || echo "$FAILS CHECK(S) FAILED"
exit $([ $FAILS -eq 0 ] && echo 0 || echo 1)
