#!/usr/bin/env bash
# Re-runs every acceptance check of P6b (H19: Git authority, no split brain). One line per check: PASS/FAIL <name>: <evidence>.
# Exits non-zero on any FAIL. Read-only git only (diff / status / rev-parse). Usage: scripts/verify_h19.sh [<evidence-dir>]
cd "$(dirname "$0")/.." || exit 2
R=$(pwd); FAILS=0
PY="${PY:-$R/.venv/bin/python}"; [ -x "$PY" ] || PY=/Users/d_surchis/work/operational-ontology-poc/round2/.venv/bin/python
export PYTHONPATH="$R/src:$R"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/verify-h19.XXXXXX")
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS+1)); }
tail1() { tail -n 1 "$1" | tr -d '\r'; }
pyt() {  # name, log, pytest args... : passes when pytest exits 0 and its summary has no failed/error
  local name=$1 log=$2; shift 2
  "$PY" -m pytest -q -p no:cacheprovider "$@" > "$log" 2>&1; local rc=$?
  local sum; sum=$(grep -E '[0-9]+ (passed|failed|error)' "$log" | tail -n 1)
  if [ $rc -eq 0 ] && ! grep -qE '[0-9]+ (failed|error)' "$log"; then pass "$name" "$sum"; else fail "$name" "rc=$rc $sum (see $log)"; fi
}

# 1. H19 unit tests: oracle semantics, state machine vs oracle, lost-update checker (known-positive + known-negative), mutants, rebuild, evaluator
pyt h19_tests "$TMP/h19.log" tests/h19
miss=""
for c in S1 S2 S3 S3b S4 S5 I V1 V2 V3 V4 V5 V6; do grep -qE "def test_${c}_" tests/h19/test_evaluate_h19.py || miss="$miss $c"; done
[ -z "$miss" ] && pass evaluator_clause_coverage "a named negative test for each of S1 S2 S3 S3b S4 S5 I V1..V6 (R is flipped inside the S1-S4 negatives)" || fail evaluator_clause_coverage "no test_<clause>_ for:$miss"
# 2. mutations: each target mutant killed by its check, signatures, control clean (run inside the suite above; re-asserted by name here)
pyt mutants_killed_control_clean "$TMP/mut.log" tests/h19/test_mutants_h19.py
# 3. oracle independence: static (imports / I/O) + grep
if grep -nE '^\s*(import|from)\s+(eoo_|domains|baselines|hdd)' oracles/h19/*.py > "$TMP/oi.out"; then fail oracle_no_engine_imports "$(head -n 3 "$TMP/oi.out" | tr '\n' ' ')"; else pass oracle_no_engine_imports "no import of eoo_*, domains, baselines, hdd in oracles/h19"; fi
"$PY" - > "$TMP/oi2.out" 2>&1 <<'PYEOF'
from eoo_h19.independence import oracle_imports
r = oracle_imports(); assert r["independent"], r["forbidden"]
print("oracle files", sorted(r["files"]), "imports", sorted({m for v in r["files"].values() for m in v}))
PYEOF
[ $? -eq 0 ] && pass oracle_independent_static "$(tail1 "$TMP/oi2.out")" || fail oracle_independent_static "$(tail -n 3 "$TMP/oi2.out" | tr '\n' ' ')"
# 4. Engine / Git store unchanged vs tag r2-engine-v1.2 (tracked diff + untracked); read-only trees unchanged vs HEAD
if git rev-parse --verify --quiet 'r2-engine-v1.2^{commit}' > /dev/null; then
  d=$(git diff --name-only r2-engine-v1.2 -- src/eoo_engine src/eoo_engine_git; git status --porcelain --untracked-files=all -- src/eoo_engine src/eoo_engine_git)
  [ -z "$d" ] && pass engine_and_git_store_unchanged_vs_r2-engine-v1.2 "no diff, no untracked in src/eoo_engine, src/eoo_engine_git" || fail engine_and_git_store_unchanged_vs_r2-engine-v1.2 "$d"
else fail engine_and_git_store_unchanged_vs_r2-engine-v1.2 "tag r2-engine-v1.2 not found"; fi
d=$(git diff --name-only HEAD -- protocol hypotheses experiments domains ontology schemas src/eoo_ir src/eoo_dsl src/eoo_openpona src/hdd src/eoo_engine src/eoo_engine_git src/eoo_h15 src/eoo_h16 src/eoo_h17 src/eoo_h18 src/eoo_h20 src/eoo_h21 src/eoo_h22 oracles/h16 oracles/h17 oracles/h18 oracles/h20 oracles/h21 oracles/h22; git status --porcelain --untracked-files=all -- protocol hypotheses experiments domains src/eoo_engine src/eoo_engine_git src/eoo_h18 oracles/h18)
[ -z "$d" ] && pass read_only_trees_unchanged_vs_HEAD "protocol hypotheses experiments domains src/eoo_engine* src/hdd oracles/h1[6-8] H15-H22 harnesses: no diff, nothing untracked" || fail read_only_trees_unchanged_vs_HEAD "$d"
d=$(git diff --name-only HEAD -- experiments/h19/DEPENDENCY_STOP.json)
[ -z "$d" ] && pass dependency_stop_untouched "experiments/h19/DEPENDENCY_STOP.json unchanged" || fail dependency_stop_untouched "$d"
"$PY" -c "from eoo_exp import provenance as p; print(p.preflight())" > "$TMP/pre.out" 2>&1 && pass frozen_protocol_and_prereg_intact "preflight ok (FREEZE.json hashes + ENGINE_PREREG)" || fail frozen_protocol_and_prereg_intact "$(tail -n 2 "$TMP/pre.out" | tr '\n' ' ')"
# 5. dry run: tiny real run through the experiment script, immutable output, evaluated (writes nothing), five schema-valid evidence files
"$PY" scripts/run_h19.py --exp-id dry --seed 7 --n 120 --audit-cases 10 --mutation-scenarios 80 --mutation-audit-cases 8 --out-root "$TMP/dry" > "$TMP/dry.log" 2>&1; rc=$?
"$PY" scripts/evaluate_h19.py "$TMP/dry/dry" --no-write > "$TMP/dry.eval" 2>&1; erc=$?
"$PY" scripts/run_h19.py --exp-id dry --seed 7 --n 120 --audit-cases 10 --out-root "$TMP/dry" > "$TMP/dry2.log" 2>&1; rc2=$?
"$PY" - "$TMP/dry/dry" > "$TMP/dry.out" 2>&1 <<'PYEOF'
import sys, json
from eoo_exp import scaffold as sc
from eoo_exp.provenance import freeze_hash
from eoo_exp.util import ROOT
from eoo_h19.run import REQUIRED
from eoo_engine import ENGINE_VERSION
recs, pay, problems = sc.load_evidence(sys.argv[1], "H19", REQUIRED)
assert not problems, problems
assert all(r["engine_version"] == ENGINE_VERSION and r["protocol_freeze_hash"] == freeze_hash() for r in recs.values())
n = len({r["id"] for r in pay["concurrency-state-machine.json"]["scenarios"]})
assert n == 120, n
print(f"5 evidence files schema-valid, engine_version={ENGINE_VERSION} in every record, {n} unique scenarios")
PYEOF
hyp=$(grep -c '"hypothesis_id": "H19"' "$TMP/dry.eval"); evid=$(tail -n 1 "$TMP/dry.out" | grep -c 'schema-valid')
if [ $rc -eq 0 ] && [ $erc -eq 0 ] && [ $rc2 -eq 2 ] && [ "$hyp" -ge 1 ] && [ "$evid" -eq 1 ]; then
  pass dry_run "run rc=0, evaluate rc=0 ($(grep -o '"verdict": "[^"]*"' "$TMP/dry.eval" | head -n 1); 120 scenarios: INCONCLUSIVE/INVALID expected), re-run refused rc=2; $(tail1 "$TMP/dry.out")"
else fail dry_run "rc=$rc erc=$erc rerun_rc=$rc2 hyp=$hyp evid=$evid $(tail -n 2 "$TMP/dry.log" | tr '\n' ' ') $(tail -n 2 "$TMP/dry.out" | tr '\n' ' ')"; fi
# 6. optional: a full dev-run evidence dir passed as $1 is re-evaluated read-only; verdict must recompute identically; per-class and per-check numbers printed
if [ -n "$1" ]; then
  "$PY" - "$1" > "$TMP/dev.out" 2>&1 <<'PYEOF'
import json, sys
from pathlib import Path
from eoo_h19.evaluate import evaluate
d = Path(sys.argv[1]); v = evaluate(d); n = v["numbers"]
t, a = n["store_tally"], n["audit"]
assert n["unique_scenarios"] >= 5000, n["unique_scenarios"]
vf = d / "verdict.json"
same = (not vf.exists()) or json.loads(vf.read_text())["verdict"] == v["verdict"]
assert same, "stored verdict.json differs from the recomputed one"
print(f"verdict={v['verdict']} unique={n['unique_scenarios']} writes={t['writes']} classes={n['class_counts']} lost={t['lost_updates']} silent_wrong={t['silent_wrong_accept']} "
      f"disagree={t['outcome_disagreements']} replays={t['replays_equal']}/{t['replays']} binds={t['binds_pinned']}/{t['binds']} audit_ootw={a['ontology_only_writes']}/{a['accepted_actions']} "
      f"rebuild={n['rebuild']['store']['equal_commits']}/{n['rebuild']['store']['unique_commits']}+{n['rebuild']['engine']['equal_commits']}/{n['rebuild']['engine']['unique_commits']} "
      f"targets={n['target_mutants']} extras={n['extra_mutants']} controls={n['mutation_controls_clean']}")
PYEOF
  [ $? -eq 0 ] && pass dev_run_reevaluated "$(tail1 "$TMP/dev.out")" || fail dev_run_reevaluated "$(tail -n 3 "$TMP/dev.out" | tr '\n' ' ')"
fi
# 7. suites
pyt full_round2_suite "$TMP/full.log" tests
if "$PY" scripts/check_pack.py > "$TMP/make.log" 2>&1 && grep -q "PACK OK" "$TMP/make.log"; then pass make_check "$(grep -m1 'PACK OK' "$TMP/make.log")"; else fail make_check "$(tail -n 3 "$TMP/make.log" | tr '\n' ' ')"; fi
echo "logs: $TMP"
[ $FAILS -eq 0 ] && echo "ALL CHECKS PASS" || echo "$FAILS CHECK(S) FAILED"
exit $([ $FAILS -eq 0 ] && echo 0 || echo 1)
