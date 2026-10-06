#!/usr/bin/env bash
# Re-runs every acceptance check of the P5a (H16) spec. One line per check:
#   PASS <name>: <evidence>   |   FAIL <name>: <evidence>
# Exit status is non-zero if any check fails.  EXP=<id> picks the evidence dir (default exp-h16-001); SEED defaults to 16.
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
PY="$R2/.venv/bin/python"
TMP="$(cd "$(mktemp -d)" && pwd -P)"
EXP="${EXP:-exp-h16-001}"; SEED="${SEED:-16}"
FAILS=0
trap 'rm -rf "$TMP"' EXIT
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS + 1)); }
summary() { grep -aE '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error).* =+$|[0-9]+ (passed|failed|errors?)( |,|$)' "$1" | tail -1; }
emit() { while IFS= read -r line; do echo "$line"; case "$line" in FAIL*) FAILS=$((FAILS + 1));; esac; done < "$1"; }
cd "$R2" || exit 2
DIR="$R2/experiments/h16/$EXP"

# 1. H16 unit/property tests under both Hypothesis profiles; required tests present by name and passing.
for prof in dev ci; do
  HYPOTHESIS_PROFILE=$prof "$PY" -m pytest -q -p no:cacheprovider tests/h16 --junitxml="$TMP/h16_$prof.xml" > "$TMP/h16_$prof.log" 2>&1
  rc=$?; s="$(summary "$TMP/h16_$prof.log")"
  if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/h16_$prof.log"; then pass "h16_tests_$prof" "rc=0; $s"
  else fail "h16_tests_$prof" "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/h16_$prof.log" | head -5 | tr '\n' ' ')"; fi
done
"$PY" - "$TMP/h16_ci.xml" > "$TMP/required.txt" 2>&1 <<'PYEOF'
import sys, xml.etree.ElementTree as ET
req = {
 "evaluator_known_positive": "test_known_positive_is_supported",
 "evaluator_new_kind_rejected": "test_new_kernel_kind_is_rejected",
 "evaluator_domain_branch_rejected": "test_domain_branch_hit_is_rejected",
 "evaluator_rename_broken_rejected": "test_rename_invariance_broken_is_rejected",
 "evaluator_missing_requirement_inconclusive": "test_missing_requirement_is_inconclusive",
 "evaluator_too_few_cases_inconclusive": "test_too_few_cases_is_inconclusive",
 "evaluator_load_failure_inconclusive": "test_load_failure_in_generated_is_inconclusive",
 "evaluator_survivor_blocks_support": "test_surviving_mutant_blocks_support",
 "evaluator_invalid_control": "test_dirty_mutation_control_is_invalid",
 "evaluator_invalid_protocol_hash": "test_wrong_protocol_hash_is_invalid",
 "evaluator_invalid_prereg_hash": "test_wrong_prereg_hash_is_invalid",
 "evaluator_invalid_provenance": "test_disagreeing_provenance_is_invalid",
 "evaluator_invalid_kernel_freeze": "test_changed_kernel_freeze_is_invalid",
 "evaluator_missing_evidence": "test_missing_evidence_never_supports",
 "evaluator_tampered_payload": "test_tampered_payload_never_supports",
 "audit_planted_identity": "test_planted_identity_is_caught",
 "audit_known_negative": "test_known_negative_is_clean",
 "audit_real_core_clean": "test_real_core_is_clean_and_the_audit_is_not_vacuous",
 "kernel_before_after_identical": "test_before_and_after_kernels_are_identical",
 "kernel_new_dispatch_kind": "test_new_dispatch_kind_is_a_new_primitive",
 "kernel_new_schema_array": "test_new_schema_array_is_a_new_primitive",
 "requirements_all_covered": "test_all_registered_requirements_are_carried_by_project_resources",
 "requirements_removed_carrier": "test_removing_a_carrier_fails_that_requirement",
 "mixed_property": "test_generated_mixed_packages_validate_and_load",
 "mixed_known_negative_invalid": "test_known_negative_invalid_package_is_not_counted",
 "mutants_all_killed": "test_all_registered_target_mutants_are_killed_with_the_expected_signal",
 "mutation_controls_clean": "test_controls_are_clean_before_and_after",
}
cases = {}
for tc in ET.parse(sys.argv[1]).iter("testcase"):
    base = tc.get("name").split("[")[0]
    bad = any(c.tag in ("failure", "error", "skipped") for c in tc)
    ok, n = cases.get(base, (True, 0))
    cases[base] = (ok and not bad, n + 1)
for label, name in req.items():
    ok, n = cases.get(name, (False, 0))
    print(("PASS" if ok and n else "FAIL"), f"required_test_{label}:", f"{name} ran {n} case(s), all passed" if ok and n
          else f"{name} missing or failing (cases={n})")
PYEOF
emit "$TMP/required.txt"

# 2. Evidence: exactly the contract's required_evidence (+ verdict.json), schema-valid, payload hashes intact.
"$PY" - "$DIR" > "$TMP/ev.txt" 2>&1 <<'PYEOF'
import json, sys
from pathlib import Path
import jsonschema
d = Path(sys.argv[1]); root = Path("."); 
req = json.load(open("hypotheses/h16/contract.json"))["required_evidence"]
schema = json.load(open("schemas/evidence-record.schema.json"))
names = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
print(("PASS" if names == sorted(req + ["verdict.json"]) else "FAIL"), "evidence_files:", f"{names} vs contract {sorted(req)} + verdict.json")
sys.path.insert(0, "src")
from eoo_exp.util import canon, sha_text
bad = []
for f in req:
    try:
        r = json.load(open(d / f)); jsonschema.validate(r, schema)
        assert r["hypothesis_id"] == "H16" and r["evidence_kind"] == f[:-5] and sha_text(canon(r["payload"])) == r["payload_hash"]
        for k in ("git_commit", "protocol_freeze_hash", "engine_prereg_sha256", "seed", "input_corpus_hash", "harness_sha256", "harness_dirty", "environment"):
            assert k in r, k
    except Exception as e:
        bad.append(f"{f}: {type(e).__name__} {str(e)[:80]}")
print(("PASS" if not bad else "FAIL"), "evidence_schema_valid:", "6/6 records schema-valid, payload hash intact, provenance fields present" if not bad else bad)
g = json.load(open(d / "mixed-domain-generated.json"))["payload"]
rows = g["cases"]; uniq = len({r["sha"] for r in rows})
good = sum(1 for r in rows if r["valid"] and r["oracle_legal"] and r["loaded"] and r["sizes_match"] and r["mixes_both"])
print(("PASS" if uniq >= 2000 and good == uniq and not g["failures"] else "FAIL"), "generated_unique_count:",
      f"{uniq} unique cases (>= 2000), {good} valid+legal+loaded+mixed, {len(g['failures'])} failures, variants {g['by_variant']}")
PYEOF
emit "$TMP/ev.txt"

# 3. Verdict recomputes identically from the evidence (evaluator is a pure function), and says what the evidence says.
"$PY" - "$DIR" > "$TMP/vd.txt" 2>&1 <<'PYEOF'
import json, sys
sys.path.insert(0, "src")
from pathlib import Path
from eoo_h16.evaluate import evaluate
d = Path(sys.argv[1])
stored = json.load(open(d / "verdict.json")); fresh = evaluate(d)
same = json.dumps(stored, sort_keys=True) == json.dumps(fresh, sort_keys=True)
print(("PASS" if same else "FAIL"), "verdict_recomputes_identically:", f"stored={stored['verdict']} recomputed={fresh['verdict']} identical={same}")
vals = {r["id"]: r["value"] for rows in fresh["predicates"].values() for r in rows}
print("PASS" if fresh["problems"] == [] else "FAIL", "verdict_no_problems:", f"problems={fresh['problems']}")
print("PASS" if len(vals) == 15 else "FAIL", "verdict_all_clauses_named:", f"{len(vals)} named predicates: " + " ".join(f"{k}={v}" for k, v in sorted(vals.items())))
PYEOF
emit "$TMP/vd.txt"

# 4. Independent probes with known-negatives against the REAL artifacts (not the harness's own fixtures).
"$PY" - > "$TMP/probe.txt" 2>&1 <<'PYEOF'
import json, sys
sys.path.insert(0, "src")
from eoo_exp.util import ROOT
from eoo_h16.audit import collect_tokens, exempt_words, read_dir, scan_sources
from eoo_h16.detectors import kernel_diff
from eoo_h16.kernel import live_snapshot, rev_snapshot
T, EX = collect_tokens(), exempt_words()
src = read_dir(ROOT / "src/eoo_engine")
clean = scan_sources(src, T, EX)
print(("PASS" if clean["branch_hits"] == 0 and clean["literal_hits"] == 0 and clean["string_constants_scanned"] > 1000 else "FAIL"),
      "probe_core_has_no_domain_identity:", f"{clean['files_scanned']} files, {clean['string_constants_scanned']} string constants, 0 hits")
# known negatives: plant a domain-name branch into each of three real core files; each must be flagged exactly once.
for fname, plant in (("src/eoo_engine/registry.py", '\nif False and model.package_id == "project-ontology":\n    pass\n'),
                     ("src/eoo_engine/pipeline.py", '\n_X = {"manufacturing": 1}\n'),
                     ("src/eoo_engine/gates.py", '\n_Y = ("Hypothesis" in ("Hypothesis", "Part"))\n')):
    m = dict(src); m[fname] = m[fname] + plant
    r = scan_sources(m, T, EX)
    print(("PASS" if r["branch_hits"] >= 1 else "FAIL"), f"probe_planted_branch_{fname.split('/')[-1]}:", f"branch_hits={r['branch_hits']} literal_hits={r['literal_hits']}")
b = rev_snapshot("r2-engine-core")
print(("PASS" if kernel_diff(b, live_snapshot())["new_kernel_primitive_kind_count"] == 0 else "FAIL"), "probe_live_kernel_equals_prereg_commit:",
      f"before={b['git_commit'][:7]} kinds={len(b['kernel_resource_kinds'])} new_kinds=0")
ps = json.load(open("protocol/ENGINE_PREREG.json")); ps["kernel_snapshot"]["kernel_resource_kinds"].append("quantities")
d = kernel_diff(b, live_snapshot(prereg_text=json.dumps(ps)))
print(("PASS" if d["new_kernel_primitive_kinds"] == ["quantities"] else "FAIL"), "probe_planted_kernel_kind_detected:", f"new_kinds={d['new_kernel_primitive_kinds']}")
PYEOF
emit "$TMP/probe.txt"
dom="$(grep -nE "manufacturing|operational-ontology-poc|project-ontology|Hypothesis|transfer_inventory" src/eoo_engine/*.py | grep -v '^[^:]*:[0-9]*:\s*#' | head -3)"
[ -z "$dom" ] && pass grep_core_domain_tokens "grep of domain ids/names in src/eoo_engine: 0 hits" || fail grep_core_domain_tokens "$dom"
imp="$(grep -nE "^(from|import) +(eoo_engine|eoo_toolchain|domains)" oracles/h16/*.py)"
[ -z "$imp" ] && pass oracle_independent "oracles/h16 imports no eoo_engine/eoo_toolchain/domains" || fail oracle_independent "$imp"
big="$(wc -l src/eoo_h16/*.py src/eoo_exp/*.py | awk '$2 != "total" && $1 >= 250 {print $2"="$1}')"
[ -z "$big" ] && pass module_size "all eoo_h16/eoo_exp modules < 250 lines (max $(wc -l src/eoo_h16/*.py src/eoo_exp/*.py | awk '$2 != "total"' | sort -n | tail -1 | awk '{print $2"="$1}'))" || fail module_size "$big"

# 5. Runner: refuses to overwrite; a fresh small run writes exactly the six files; the frozen-size run is reproducible
#    (same seed -> same corpus hash and same verdict) when re-run into a scratch root.
"$PY" scripts/run_h16.py --exp-id exp-h16-001 --seed "$SEED" --n 10 --out-root "$R2/experiments/h16" > "$TMP/refuse.log" 2>&1
[ $? -eq 2 ] && grep -q REFUSED "$TMP/refuse.log" && pass runner_refuses_overwrite "existing $EXP dir -> exit 2 REFUSED" || fail runner_refuses_overwrite "$(tail -2 "$TMP/refuse.log")"
"$PY" scripts/run_h16.py --exp-id small --seed 3 --n 30 --out-root "$TMP/small" > "$TMP/small.log" 2>&1
n=$(ls "$TMP/small/small" 2>/dev/null | wc -l | tr -d ' '); [ "$n" = 6 ] && [ ! -e "$TMP/small/.small.partial" ] && pass runner_small_run "6 evidence files, no .partial left" || fail runner_small_run "files=$n $(tail -2 "$TMP/small.log")"
"$PY" scripts/evaluate_h16.py "$TMP/small/small" --no-write > "$TMP/small_eval.log" 2>&1
grep -q '"verdict": "INCONCLUSIVE"' "$TMP/small_eval.log" && pass evaluator_small_sample_inconclusive "n=30 run -> INCONCLUSIVE (sample below the frozen 2000)" || fail evaluator_small_sample_inconclusive "$(head -4 "$TMP/small_eval.log")"
"$PY" scripts/run_h16.py --exp-id repro --seed "$SEED" --out-root "$TMP/repro" > "$TMP/repro.log" 2>&1
"$PY" - "$DIR" "$TMP/repro/repro" > "$TMP/repro.txt" 2>&1 <<'PYEOF'
import json, sys
sys.path.insert(0, "src")
from eoo_h16.evaluate import evaluate
a, b = sys.argv[1:3]
ca = json.load(open(a + "/mixed-domain-generated.json"))["input_corpus_hash"]
cb = json.load(open(b + "/mixed-domain-generated.json"))["input_corpus_hash"]
va, vb = evaluate(a)["verdict"], evaluate(b)["verdict"]
pa = json.load(open(a + "/core-diff.json"))["payload"]; pb = json.load(open(b + "/core-diff.json"))["payload"]
ok = ca == cb and va == vb and pa["new_kernel_primitive_kind_count"] == pb["new_kernel_primitive_kind_count"]
print(("PASS" if ok else "FAIL"), "rerun_reproduces:", f"corpus_hash equal={ca == cb} verdict {va} vs {vb}")
PYEOF
emit "$TMP/repro.txt"

# 6. Frozen / read-only files untouched; only allowed new paths.
"$PY" - > "$TMP/frozen.txt" 2>&1 <<'PYEOF'
import json, sys, hashlib
sys.path.insert(0, "src")
from eoo_exp.provenance import freeze_hash, prereg_sha
from eoo_exp.util import sha_file, ROOT, git
fz = json.load(open("protocol/FREEZE.json"))
bad = [f["path"] for f in fz["files"] if sha_file(ROOT / f["path"]) != f["sha256"]]
print(("PASS" if not bad and freeze_hash() == fz["protocol_sha256"] else "FAIL"), "frozen_files_unchanged:", f"{len(fz['files'])} files match FREEZE.json; protocol hash {freeze_hash()[:12]}; bad={bad}")
head = git("show", "HEAD:round2/protocol/ENGINE_PREREG.json")
print(("PASS" if hashlib.sha256(head.encode()).hexdigest() == prereg_sha() else "FAIL"), "engine_prereg_unchanged:", f"sha256 {prereg_sha()[:12]} equals the HEAD blob")
PYEOF
emit "$TMP/frozen.txt"
ro="$(git status --porcelain -- protocol hypotheses domains src/eoo_engine src/eoo_ir src/eoo_dsl src/eoo_openpona experiments/h15 ontology docs tests/engine tests/domains tests/h15)"
[ -z "$ro" ] && pass read_only_paths_untouched "git status on protocol/ hypotheses/ domains/ eoo_engine/ir/dsl/openpona experiments/h15 ontology docs tests/{engine,domains,h15}: clean" || fail read_only_paths_untouched "$ro"
changed="$(git status --porcelain -u -- . | awk '{print $2}')"
bad=""
for f in $changed; do
  case "${f#round2/}" in
    src/eoo_exp/*|src/eoo_h16/*|tests/h16/*|oracles/*|scripts/run_h16.py|scripts/evaluate_h16.py|scripts/verify_h16.sh|experiments/h16/*) ;;
    *) bad="$bad $f";;
  esac
done
[ -z "$bad" ] && pass repo_scope "only new H16/eoo_exp/oracles paths: $(echo $changed | tr '\n' ' ' | cut -c1-300)" || fail repo_scope "unexpected:$bad"

# 7. Whole round2 suite and pack check.
"$PY" -m pytest -q -p no:cacheprovider > "$TMP/full.log" 2>&1
rc=$?; s="$(summary "$TMP/full.log")"
if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/full.log"; then pass full_round2_suite "rc=0; $s"
else fail full_round2_suite "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/full.log" | head -5 | tr '\n' ' ')"; fi
(PATH="$R2/.venv/bin:$PATH" make check > "$TMP/check.log" 2>&1)
grep -aq "PACK OK" "$TMP/check.log" && pass make_check "$(grep -a 'PACK OK' "$TMP/check.log")" || fail make_check "$(tail -3 "$TMP/check.log" | tr '\n' ' ')"

echo "SUMMARY: $FAILS failing check(s)"
[ "$FAILS" -eq 0 ]
