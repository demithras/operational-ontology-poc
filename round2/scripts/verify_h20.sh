#!/usr/bin/env bash
# Re-runs every acceptance check of the P7 (H20) spec. One line per check:
#   PASS <name>: <evidence>   |   FAIL <name>: <evidence>
# Exit status is non-zero if any check fails.  EXP=<id> picks the evidence dir (default exp-h20-dev); SEED defaults to 20.
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
PY="$R2/.venv/bin/python"
TMP="$(cd "$(mktemp -d)" && pwd -P)"
EXP="${EXP:-exp-h20-dev}"; SEED="${SEED:-20}"
FAILS=0
trap 'rm -rf "$TMP"' EXIT
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS + 1)); }
summary() { grep -aE '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error).* =+$|[0-9]+ (passed|failed|errors?)( |,|$)' "$1" | tail -1; }
emit() { while IFS= read -r line; do echo "$line"; case "$line" in FAIL*) FAILS=$((FAILS + 1));; esac; done < "$1"; }
cd "$R2" || exit 2
DIR="$R2/experiments/h20/$EXP"

# 1. Step 0 prerequisite (H16 kernel tests) and the H20 unit/property tests under both Hypothesis profiles.
"$PY" -m pytest -q -p no:cacheprovider tests/h16/test_kernel.py > "$TMP/k.log" 2>&1; rc=$?
if [ $rc -eq 0 ] && grep -aq "test_kernel_kinds_dispatch_schema_at_head_equal_engine_core" tests/h16/test_kernel.py && grep -aq 'rev_snapshot("r2-h16-exp001")' tests/h16/test_kernel.py; then
  pass step0_h16_kernel_tests "rc=0; $(summary "$TMP/k.log"); 'after' snapshot = tag r2-h16-exp001; separate test pins kernel kinds/dispatch/schema at HEAD to r2-engine-core"
else fail step0_h16_kernel_tests "rc=$rc; $(summary "$TMP/k.log"); $(grep -aE '^FAILED' "$TMP/k.log" | head -3 | tr '\n' ' ')"; fi
git diff -U0 -- tests/h16/test_kernel.py | grep -aE '^[-+][^-+]' | grep -aqE 'assert.*(new_kernel_primitive_kind_count|dispatch_kinds_equal_schema_arrays|schema_unchanged)' \
  && ! git diff -U0 -- tests/h16/test_kernel.py | grep -aE '^-[^-]' | grep -aqE 'assert.*(new_kernel_primitive_kind_count|dispatch_kinds_equal_schema_arrays|schema_unchanged)' \
  && pass step0_kind_checks_not_weakened "no kind/dispatch/schema assert line was removed from tests/h16/test_kernel.py (they are kept and also applied at HEAD)" \
  || fail step0_kind_checks_not_weakened "$(git diff -U0 -- tests/h16/test_kernel.py | grep -aE '^-[^-]' | head -5)"
for prof in dev ci; do
  HYPOTHESIS_PROFILE=$prof "$PY" -m pytest -q -p no:cacheprovider tests/h20 --junitxml="$TMP/h20_$prof.xml" > "$TMP/h20_$prof.log" 2>&1
  rc=$?; s="$(summary "$TMP/h20_$prof.log")"
  if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/h20_$prof.log"; then pass "h20_tests_$prof" "rc=0; $s"
  else fail "h20_tests_$prof" "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/h20_$prof.log" | head -5 | tr '\n' ' ')"; fi
done
"$PY" - "$TMP/h20_ci.xml" > "$TMP/required.txt" 2>&1 <<'PYEOF'
import sys, xml.etree.ElementTree as ET
req = {
 "closure_complete": "test_closure_contains_every_engine_file_and_the_ir_validator",
 "closure_case_exact": "test_closure_is_case_exact",
 "closure_follows_planted_import": "test_closure_follows_a_planted_import",
 "closure_dynamic_import_known_negative": "test_closure_reports_a_dynamic_import_site",
 "static_real_tree_clean": "test_real_tree_is_clean",
 "static_token_known_negatives": "test_token_scan_known_negatives",
 "static_identity_branch_tokenless": "test_identity_branch_scan_sees_a_tokenless_branch",
 "oracle_independent": "test_oracles_import_no_engine_or_domain_code",
 "oracle_import_checker_known_negative": "test_oracle_import_checker_catches_a_planted_import",
 "adapter_real_clean": "test_real_adapters_are_clean_with_one_declared_exception",
 "adapter_planted_governance": "test_planted_governance_is_flagged",
 "adapter_engine_import": "test_planted_engine_governance_import_is_flagged",
 "adapter_taint_known_negative": "test_taint_known_negative_sees_a_journal_write_from_an_adapter",
 "adapter_engine_owns_idempotency": "test_engine_owns_the_idempotency_decision",
 "adapter_ok_mode_probe": "test_ok_mode_probe_is_clean_and_sees_a_refusing_adapter",
 "synth_valid_ir": "test_generated_packages_are_valid_ir_over_existing_kinds",
 "synth_engine_equals_oracle": "test_engine_agrees_with_the_oracle_on_every_generated_definition",
 "synth_broken_engine_caught": "test_a_broken_engine_is_caught_by_the_oracle_comparison",
 "alias_probe_known_negative": "test_alias_probe_is_quiet_on_the_real_engine_and_loud_on_a_name_keyed_engine",
 "lifecycle_oracle_vs_engine_table": "test_oracle_lifecycle_equals_the_engine_transition_table",
 "lifecycle_known_negatives": "test_frozen_lifecycle_known_positive_and_negatives",
 "trace_profile_participation": "test_profile_hook_attributes_files_to_dispatch",
 "mutants_all_detected": "test_every_target_mutant_is_detected_and_controls_are_clean",
 "mutants_two_signals": "test_engine_mutants_are_caught_by_both_independent_signals",
 "mutants_blind_spot_disclosed": "test_the_vocabulary_audit_misses_an_innocuous_name_and_the_probe_does_not",
 "mutants_noop_survives": "test_a_noop_edit_is_not_flagged",
 "evaluator_known_positive": "test_known_positive_is_supported",
 "evaluator_s1_reject": "test_s1_and_r1_a_domain_branch_in_the_engine_is_rejected",
 "evaluator_s2_lifecycle": "test_s2_a_lifecycle_violation_is_inconclusive_not_supported",
 "evaluator_s3_reject": "test_s3_governance_in_an_adapter_is_rejected",
 "evaluator_s4_engine_edit": "test_s4_an_edited_engine_blocks_support",
 "evaluator_s5_survivor": "test_s5_a_surviving_mutant_blocks_support",
 "evaluator_r1_alias": "test_r1_alias_dependent_behaviour_is_rejected",
 "evaluator_i1_paths": "test_i1_a_domain_missing_a_path_is_inconclusive",
 "evaluator_i2_sample": "test_i2_too_few_unique_definitions_is_inconclusive",
 "evaluator_i3_suite": "test_i3_a_failing_domain_suite_is_inconclusive",
 "evaluator_v1_unscanned": "test_v1_an_unscanned_participating_file_is_invalid",
 "evaluator_v2_hash": "test_v2_wrong_protocol_hash_is_invalid",
 "evaluator_v3_provenance": "test_v3_disagreeing_provenance_is_invalid",
 "evaluator_v4_oracle": "test_v4_oracle_importing_the_engine_is_invalid",
 "evaluator_v5_dirty": "test_v5_dirty_engine_files_are_invalid",
 "evaluator_missing_evidence": "test_missing_evidence_never_supports",
 "evaluator_tampered_payload": "test_tampered_payload_never_supports",
 "evaluator_all_clauses": "test_every_contract_clause_has_a_named_predicate",
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

# 2. Evidence: exactly the contract's required_evidence (+ verdict.json), schema-valid, payload hashes intact, sizes as frozen.
"$PY" - "$DIR" > "$TMP/ev.txt" 2>&1 <<'PYEOF'
import json, sys, hashlib
from pathlib import Path
import jsonschema
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from eoo_exp.util import canon, sha_text, sha_file
d = Path(sys.argv[1])
con = json.load(open("hypotheses/h20/contract.json"))
req = con["required_evidence"]; minimum = con["experiment"]["minimum_runs"]
schema = json.load(open("schemas/evidence-record.schema.json"))
names = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
print(("PASS" if names == sorted(req + ["verdict.json"]) else "FAIL"), "evidence_files:", f"{names} vs contract {sorted(req)} + verdict.json")
bad, pay, recs = [], {}, {}
for f in req:
    try:
        r = json.load(open(d / f)); jsonschema.validate(r, schema)
        assert r["hypothesis_id"] == "H20" and r["evidence_kind"] == f[:-5] and sha_text(canon(r["payload"])) == r["payload_hash"]
        for k in ("git_commit", "protocol_freeze_hash", "engine_prereg_sha256", "seed", "input_corpus_hash", "harness_sha256", "harness_dirty", "environment", "engine_version"):
            assert k in r, k
        pay[f] = r["payload"]; recs[f] = r
    except Exception as e:
        bad.append(f"{f}: {type(e).__name__} {str(e)[:80]}")
print(("PASS" if not bad else "FAIL"), "evidence_schema_valid:", "5/5 records schema-valid, payload hash intact, provenance fields present" if not bad else bad)
ev = {r["engine_version"] for r in recs.values()}
c = pay["synthetic-resource-results.json"]["candidate"]
print(("PASS" if ev == {"1.1"} and c["engine_tag"] == "r2-engine-v1.1" else "FAIL"), "evidence_names_engine_version:", f"ENGINE_VERSION {sorted(ev)}, tag {c['engine_tag']} -> {c['engine_tag_commit'][:12]}, run at HEAD {c['head'][:12]}")
st, tr, ad, sy, mu = (pay[f] for f in req)
# static audit scope: scanned list == import closure, includes the Git-backed store and eoo_ir, nothing under domains/
files = st["closure"]["files"]
need = [f for f in files if not f.startswith(("src/eoo_engine/", "src/eoo_engine_git/", "src/eoo_ir/"))]
has_git = any(f.startswith("src/eoo_engine_git/") for f in files)
print(("PASS" if sorted(files) == sorted(st["file_sha256"]) and has_git and not need and st["forbidden_core_branches"] == 0 and st["forbidden_core_literals"] == 0 else "FAIL"),
      "static_audit:", f"{len(files)} files scanned (= import closure of src/eoo_engine*, incl. eoo_engine_git and eoo_ir), {st['string_constants_scanned']} string constants vs {st['token_count']} domain identifiers: "
      f"{st['token_branch_hits']} branch hits, {st['token_literal_hits']} literal hits, {len(st['identity_branch_hits'])} identity-in-branch; extra files {need}")
pa = st["participation"]
print(("PASS" if not pa["unscanned_participants"] and not st["closure"]["dynamic_import_sites"] else "FAIL"), "static_audit_scope_complete:",
      f"files executed inside dispatch: {len(pa['scanned_engine_closure'])} in the closure, {len(pa['binding_side'])} binding-side (domains/** + what they import), {len(pa['harness_side'])} harness-side, "
      f"unscanned participants {pa['unscanned_participants']}, dynamic import sites {st['closure']['dynamic_import_sites']}")
# traces
from collections import Counter
sys.path.insert(0, ".")
from eoo_exp.util import load_oracle
L = load_oracle("h20", "lifecycle")
dm = tr["domains"]
nonc = {x: sum(c for h, c in dm[x]["executions"]["history_counts"].items() if L.history_problem(h.split(" > "))) for x in dm}
cov = {x: dm[x]["actions"]["coverage"] for x in dm}
print(("PASS" if all(v == 0 for v in nonc.values()) and all(v == 1.0 for v in cov.values()) and not any(dm[x]["dispatch_outside_generic_set"] for x in dm) else "FAIL"), "dispatch_traces_generic_lifecycle:",
      f"executions { {x: dm[x]['executions']['count'] for x in dm} }, nonconforming {nonc}, action coverage {cov}, dispatch outside the frozen kind-keyed set {[dm[x]['dispatch_outside_generic_set'] for x in dm]}, "
      f"distinct histories { {x: len(dm[x]['executions']['history_counts']) for x in dm} }, handler objects per kind single={tr['cross_domain']['handler_object_per_kind_is_single']}")
pp = {x: dm[x]["paths"] for x in dm}
ok = all(p["read_dispatches"] and p["function_dispatches"] and p["governed_action_executions"] and p["security_authority_decisions"] and p["security_authority_denials"] and p["provenance_records"] for p in pp.values())
print(("PASS" if ok else "FAIL"), "dispatch_traces_paths_exercised:", json.dumps({x: {k: p[k] for k in ("read_dispatches", "function_dispatches", "governed_action_executions", "security_authority_decisions", "security_authority_denials", "provenance_records")} for x, p in pp.items()}))
su = tr["suites"]
print(("PASS" if su["pytest"]["exit_code"] == 0 and su["pytest"]["failed"] == 0 and su["pytest"]["passed"] > 50 and all(v["failures"] == 0 and v["examples"] > 0 for v in su["state_machine_sample"].values()) else "FAIL"),
      "traced_workloads:", f"pytest {su['pytest']['args']}: {su['pytest']['passed']} passed {su['pytest']['failed']} failed; H17 machine sample {su['state_machine_sample']}; generic sweep actions {[len(v['actions_proposed']) for v in su['generic_sweep'].values()]}")
# adapters
s = ad["static"]; dy = ad["dynamic"]
viol = sum(len(r["violations"]) for r in s["files"])
adapters_listed = [r["file"] for r in s["files"]]
cov_ok = all(any(a.endswith(x) for a in adapters_listed) for x in ("wms_fake.py", "erp_mes_fake.py", "git_fake.py", "eoo_engine_git/adapter.py", "eoo_engine_git/store.py"))
print(("PASS" if viol == 0 and cov_ok and not dy["governance_calls_inside_adapters"] and dy["taint_known_negative"]["detected"] else "FAIL"), "adapter_audit:",
      f"{len(adapters_listed)} adapter files (domains/*/adapters/* + src/eoo_engine_git/*), static violations {viol}, declared exception hits {sum(len(r['declared']) for r in s['files'])}, disclosed data-position uses {sum(len(r['disclosed']) for r in s['files'])}, "
      f"governance calls inside adapter methods {len(dy['governance_calls_inside_adapters'])} over {sum(dy['adapter_calls_observed'].values())} adapter calls; taint known-negative detected={dy['taint_known_negative']['detected']}")
print(("PASS" if all(r["engine_decided"] for r in dy["engine_owns_idempotency_probe"]) and all(r["carried_out"] for r in dy["ok_mode_probe"]) else "FAIL"), "adapter_dynamic_probes:",
      f"Engine-owned idempotency {[ (r['domain'], r['engine_decided']) for r in dy['engine_owns_idempotency_probe']]}; ok-mode scenarios carried out {sum(r['carried_out'] for r in dy['ok_mode_probe'])}/{len(dy['ok_mode_probe'])}")
# synthetic
R = sy["definitions"]
uniq = len({r["sha"] for r in R})
before, after = sy["engine_files_sha256_before"], sy["engine_files_sha256_after"]
print(("PASS" if uniq >= minimum and all(not r["mismatches"] for r in R) and before == after and sy["dispatch_fingerprint_before"] == sy["dispatch_fingerprint_after"] and not sy["kinds_not_in_dispatch_table"] else "FAIL"),
      "synthetic_resources:", f"{uniq} unique definitions (>= {minimum}; {sy['unique_structures']} distinct structures), {sum(1 for r in R if r['mismatches'])} oracle mismatches, Engine sha256 over {len(before)} files before==after {before == after}, "
      f"dispatch table unchanged {sy['dispatch_fingerprint_before'] == sy['dispatch_fingerprint_after']}, kinds used {sy['kinds_used']}, states {dict(Counter(r['observed_state'] for r in R))}")
al = sy["alias_invariance"]
print(("PASS" if al["disagreements"] == 0 and al["definitions"] >= 100 and not sy["synthetic_ids_equal_to_domain_tokens"] else "FAIL"), "synthetic_alias_invariance:",
      f"{al['definitions']} definitions x modes {al['modes']} (real domain package/action/type/role ids), disagreements {al['disagreements']}; synthetic ids equal to domain tokens {sy['synthetic_ids_equal_to_domain_tokens']}")
# mutation
tg = [m for m in mu["mutants"] if m["target"]]
det = [m for m in tg if m["signals"]["static_flagged"] or m["signals"]["dynamic_flagged"]]
print(("PASS" if len(det) == len(tg) and len(tg) >= 6 and mu["controls"]["clean"] else "FAIL"), "mutation_results:",
      f"{len(det)}/{len(tg)} killed, controls clean={mu['controls']['clean']}; " + "; ".join(f"{m['id'].split('_')[0]}:{'+'.join(x.split('_')[0] for x in m['detected_by'])}" for m in mu["mutants"]))
PYEOF
emit "$TMP/ev.txt"

# 3. Verdict recomputes identically from the evidence (evaluator is a pure function).
"$PY" - "$DIR" > "$TMP/vd.txt" 2>&1 <<'PYEOF'
import json, sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from pathlib import Path
from eoo_h20.evaluate import evaluate
d = Path(sys.argv[1])
stored = json.load(open(d / "verdict.json")); fresh = evaluate(d)
same = json.dumps(stored, sort_keys=True) == json.dumps(fresh, sort_keys=True)
print(("PASS" if same else "FAIL"), "verdict_recomputes_identically:", f"stored={stored['verdict']} recomputed={fresh['verdict']} identical={same}")
vals = {r["id"]: r["value"] for rows in fresh["predicates"].values() for r in rows}
print("PASS" if fresh["problems"] == [] else "FAIL", "verdict_no_problems:", f"problems={fresh['problems']}")
print("PASS" if len(vals) == 14 else "FAIL", "verdict_all_clauses_named:", f"{len(vals)} named predicates: " + " ".join(f"{k}={v}" for k, v in sorted(vals.items())))
print("INFO", "verdict_common:", json.dumps(fresh["common"]), "verdict =", fresh["verdict"])
PYEOF
emit "$TMP/vd.txt"

# 4. Independent probes (hand-written here: plain grep / tokenize / hashing, not the harness's scanners).
"$PY" - > "$TMP/probe.txt" 2>&1 <<'PYEOF'
import hashlib, io, json, re, sys, tokenize
from pathlib import Path
R = Path(".")
ids = set()
for f in ("domains/manufacturing/ir.json", "domains/project/ir.json", "domains/project/ir.v2.json"):
    pkg = json.load(open(f)); ids |= {pkg["package_id"], pkg.get("domain_id", "")} - {""}
    for k in ("object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules", "observation_types", "constraints"):
        ids |= {r["id"] for r in pkg[k]}
schema_words = set(re.findall(r'"([A-Za-z_]+)"', open("ontology/ir.schema.json").read()))
ids -= schema_words | {"identity", "authority", "policy", "preconditions"}
def quoted_hits(text):
    return sorted({m for m in re.findall(r"""['"]([^'"\n]{2,80})['"]""", text) if m in ids})
core = "".join(p.read_text() for p in sorted(Path("src/eoo_engine").glob("*.py")))
planted = core + "\nif eng.model.package_id == 'manufacturing-ontology':\n    pass\nx = 'transfer_inventory'\n"
real, neg = quoted_hits(core), quoted_hits(planted)
print("PASS" if not real and set(neg) == {"manufacturing-ontology", "transfer_inventory"} else "FAIL", "probe_core_tokens_grep:",
      f"{len(ids)} domain identifiers; quoted occurrences in src/eoo_engine: {real}; known-negative (planted branch + literal) finds {neg}")
# adapters: NAME tokens (code, not strings/comments) carrying governance words
rx = re.compile(r"polic|authori|precondition|provenance|idempot|approv|principal|lifecycle", re.I)
def names(text):
    return sorted({t.string for t in tokenize.generate_tokens(io.StringIO(text).readline) if t.type == tokenize.NAME and rx.search(t.string)})
files = sorted(Path("domains").glob("*/adapters/*.py")) + sorted(Path("src/eoo_engine_git").glob("*.py"))
found = {str(f): names(f.read_text()) for f in files}
found = {k: v for k, v in found.items() if v}
neg = names("class A:\n    def apply(self, e, p):\n        if not self._policy_allows(p):\n            raise ValueError\n")
print("PASS" if list(found) == ["src/eoo_engine_git/store.py"] and found["src/eoo_engine_git/store.py"] == ["provenance"] and neg == ["_policy_allows"] else "FAIL", "probe_adapter_names_tokenize:",
      f"{len(files)} adapter files; governance words in code NAME tokens: {found} (the one declared exception: GitStore._msg switch); known-negative planted check found {neg}")
# Engine bytes: working tree == HEAD == the hashes recorded before/after the synthetic run
import subprocess
d = Path(sys.argv[1]) if len(sys.argv) > 1 else None
PYEOF
emit "$TMP/probe.txt"
"$PY" - "$DIR" > "$TMP/probe2.txt" 2>&1 <<'PYEOF'
import hashlib, json, subprocess, sys
from pathlib import Path
d = Path(sys.argv[1])
sy = json.load(open(d / "synthetic-resource-results.json"))["payload"]
now = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path("src/eoo_engine").rglob("*.py")) if "__pycache__" not in p.parts}
rec = {k.replace("src/", "", 1): v for k, v in sy["engine_files_sha256_after"].items() if k.startswith("src/eoo_engine/")}
now = {k.replace("src/", "", 1): v for k, v in now.items()}
diff = subprocess.run(["git", "diff", "--stat", "HEAD", "--", "src/eoo_engine", "src/eoo_engine_git", "domains", "src/eoo_ir"], capture_output=True, text=True).stdout.strip()
print("PASS" if now == rec and not diff else "FAIL", "probe_engine_bytes_unchanged:", f"sha256 of {len(now)} src/eoo_engine files now == recorded after-run hashes: {now == rec}; git diff HEAD on engine/store/domains/ir: {'empty' if not diff else diff}")
# an independent hand-written package through the Engine (not the generator): fill_box from the engine test double
sys.path.insert(0, "src"); sys.path.insert(0, "tests/engine"); sys.path.insert(0, ".")
from synth import build
eng, k, carrier = build()
rec = eng.propose("fill_box", {"box": "b1", "amount": 5}, "filler", idempotency_key="ind-1")
print("PASS" if rec["state"] == "RECONCILED_SUCCESS" and eng.get("Box", "b1")["props"]["level"] == 15 and len(eng.effect_log) == 1 else "FAIL", "probe_hand_written_package:",
      f"fill_box on the engine test double -> {rec['state']}, level {eng.get('Box', 'b1')['props']['level']}, effects {len(eng.effect_log)}, history {rec['history']}")
PYEOF
emit "$TMP/probe2.txt"
imp="$(grep -nE "^(from|import) +(eoo_engine|eoo_toolchain|domains|eoo_exp|eoo_h20)" oracles/h20/*.py)"
[ -z "$imp" ] && pass oracle_independent "oracles/h20 imports no eoo_engine/eoo_toolchain/domains/eoo_h20/eoo_exp (grep)" || fail oracle_independent "$imp"
big="$(wc -l src/eoo_h20/*.py oracles/h20/*.py | awk '$2 != "total" && $1 >= 250 {print $2"="$1}')"
[ -z "$big" ] && pass module_size "all eoo_h20/oracle modules < 250 lines (max $(wc -l src/eoo_h20/*.py oracles/h20/*.py | awk '$2 != "total"' | sort -n | tail -1 | awk '{print $2"="$1}'))" || fail module_size "$big"

# 5. Runner: refuses to overwrite; a small run writes exactly the five files and is never SUPPORTED below the frozen sample.
"$PY" scripts/run_h20.py --exp-id "$EXP" --seed "$SEED" --out-root "$R2/experiments/h20" > "$TMP/refuse.log" 2>&1
[ $? -eq 2 ] && grep -q REFUSED "$TMP/refuse.log" && pass runner_refuses_overwrite "existing $EXP dir -> exit 2 REFUSED" || fail runner_refuses_overwrite "$(tail -2 "$TMP/refuse.log")"
"$PY" scripts/run_h20.py --exp-id small --seed 3 --n-synth 100 --n-machine 5 --n-probe 20 --suite tests/domains/test_manufacturing_e2e.py --out-root "$TMP/small" > "$TMP/small.log" 2>&1
n=$(ls "$TMP/small/small" 2>/dev/null | wc -l | tr -d ' '); [ "$n" = 5 ] && [ ! -e "$TMP/small/.small.partial" ] && pass runner_small_run "5 evidence files, no .partial left" || fail runner_small_run "files=$n $(tail -2 "$TMP/small.log")"
"$PY" scripts/evaluate_h20.py "$TMP/small/small" --no-write > "$TMP/small_eval.log" 2>&1
grep -Eq '"sample_sufficient": false' "$TMP/small_eval.log" && grep -Eq '"verdict": "INCONCLUSIVE"' "$TMP/small_eval.log" && pass evaluator_small_sample_not_supported "100-definition run -> sample_sufficient=false, INCONCLUSIVE (frozen minimum 3,000)" || fail evaluator_small_sample_not_supported "$(head -8 "$TMP/small_eval.log")"

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
ro="$(git status --porcelain -- protocol hypotheses domains src/eoo_engine src/eoo_engine_git src/eoo_ir src/eoo_dsl src/eoo_openpona src/eoo_exp src/eoo_h15 src/eoo_h16 src/eoo_h17 src/eoo_h18 experiments/h15 experiments/h16 experiments/h17 experiments/h18 experiments/h19 oracles/h16 oracles/h17 oracles/h18 ontology docs tests/engine tests/domains tests/h15 tests/h17 tests/h18)"
[ -z "$ro" ] && pass read_only_paths_untouched "git status on protocol/ hypotheses/ domains/ eoo_engine/ eoo_engine_git/ ir/dsl/openpona/exp/h15-h18 experiments/h15-h19 oracles/h16-h18 ontology docs tests/{engine,domains,h15,h17,h18}: clean" || fail read_only_paths_untouched "$ro"
changed="$(git status --porcelain -u -- . | awk '{print $2}')"
bad=""
for f in $changed; do
  case "${f#round2/}" in
    src/eoo_h20/*|tests/h20/*|oracles/h20/*|scripts/run_h20.py|scripts/evaluate_h20.py|scripts/verify_h20.sh|experiments/h20/*|tests/h16/test_kernel.py) ;;
    *) bad="$bad $f";;
  esac
done
[ -z "$bad" ] && pass repo_scope "only new H20 paths + the Step 0 edit of tests/h16/test_kernel.py: $(echo $changed | tr '\n' ' ' | cut -c1-300)" || fail repo_scope "unexpected:$bad"

# 7. Whole round2 suite and pack check.
"$PY" -m pytest -q -p no:cacheprovider > "$TMP/full.log" 2>&1
rc=$?; s="$(summary "$TMP/full.log")"
if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/full.log"; then pass full_round2_suite "rc=0; $s"
else fail full_round2_suite "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/full.log" | head -5 | tr '\n' ' ')"; fi
(PATH="$R2/.venv/bin:$PATH" make check > "$TMP/check.log" 2>&1)
grep -aq "PACK OK" "$TMP/check.log" && pass make_check "$(grep -a 'PACK OK' "$TMP/check.log")" || fail make_check "$(tail -3 "$TMP/check.log" | tr '\n' ' ')"

echo "SUMMARY: $FAILS failing check(s)"
[ "$FAILS" -eq 0 ]
