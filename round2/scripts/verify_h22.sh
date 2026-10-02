#!/usr/bin/env bash
# Re-runs every acceptance check of the P9 (H22) spec. One line per check:  PASS <name>: <evidence>  |  FAIL <name>: <evidence>
# Non-zero exit on any FAIL.  EXP=<id> picks the evidence dir (default exp-h22-dev).
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
PY="$R2/.venv/bin/python"
TMP="$(cd "$(mktemp -d)" && pwd -P)"
EXP="${EXP:-exp-h22-dev}"; SEED="${SEED:-22}"
FAILS=0
trap 'rm -rf "$TMP"' EXIT
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS + 1)); }
summary() { grep -aE '[0-9]+ (passed|failed|errors?)( |,|$)' "$1" | tail -1; }
emit() { while IFS= read -r line; do echo "$line"; case "$line" in FAIL*) FAILS=$((FAILS + 1));; esac; done < "$1"; }
cd "$R2" || exit 2
DIR="$R2/experiments/h22/$EXP"

# 1. Unit / property tests under both Hypothesis profiles, plus the named tests that carry each acceptance claim.
for prof in dev ci; do
  HYPOTHESIS_PROFILE=$prof "$PY" -m pytest -q -p no:cacheprovider tests/h22 --junitxml="$TMP/h22_$prof.xml" > "$TMP/h22_$prof.log" 2>&1
  rc=$?; s="$(summary "$TMP/h22_$prof.log")"
  if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/h22_$prof.log"; then pass "h22_tests_$prof" "rc=0; $s"
  else fail "h22_tests_$prof" "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/h22_$prof.log" | head -5 | tr '\n' ' ')"; fi
done
"$PY" - "$TMP/h22_ci.xml" > "$TMP/required.txt" 2>&1 <<'PYEOF'
import sys, xml.etree.ElementTree as ET
req = {
 "real_run_inconclusive_via_gate": "test_real_run_is_inconclusive_through_the_domain_gate",
 "all_clauses_named": "test_every_contract_clause_has_a_named_predicate",
 "known_positive_3_domains_30_tasks_supported": "test_known_positive_is_supported",
 "two_domains_supporting_numbers_inconclusive": "test_two_domains_with_supporting_numbers_is_inconclusive_not_supported",
 "two_domains_rejecting_numbers_inconclusive": "test_two_domains_with_rejecting_numbers_is_still_inconclusive",
 "three_domains_ratios_ge_090_rejected": "test_three_domains_all_ratios_at_least_090_is_rejected",
 "baseline_slope_rejected": "test_baseline_with_equal_or_lower_slope_is_rejected",
 "fair_baseline_tooling_rejected": "test_r2_savings_disappear_under_fair_baseline_tooling",
 "regression_rejected": "test_r2_savings_that_cost_a_regression",
 "fewer_than_30_tasks_inconclusive": "test_fewer_than_30_tasks_is_inconclusive",
 "synthetic_domain_not_counted": "test_synthetic_or_unevidenced_domain_is_not_counted",
 "stated_count_not_trusted": "test_stated_domain_count_is_not_trusted",
 "uncertainty_spans_inconclusive": "test_i1_uncertainty_spanning_support_and_reject_is_inconclusive",
 "reveal_change_invalid": "test_v1_corpus_metric_or_baseline_changed_after_reveal_is_invalid",
 "asymmetric_components_invalid": "test_v2_a_null_glue_component_is_invalid",
 "wrong_protocol_hash_invalid": "test_v3_wrong_protocol_hash_is_invalid",
 "disagreeing_provenance_invalid": "test_v4_disagreeing_provenance_is_invalid",
 "missing_evidence_never_supports": "test_missing_evidence_never_supports",
 "tampered_payload_never_supports": "test_tampered_payload_never_supports",
 "context_labelled_not_trend": "test_context_facts_are_labelled_and_read_from_committed_evidence",
 "fairness_control_clean": "test_control_is_clean",
 "fairness_mutants_detected_by_owner": "test_each_ignore_glue_mutant_is_detected_by_its_check",
 "fairness_symmetric_change_not_flagged": "test_a_symmetric_change_is_not_flagged",
 "fairness_task_level_known_negatives": "test_task_level_asymmetry_known_negatives",
 "fairness_evaluator_invalid_on_mutant": "test_evaluator_turns_a_glue_ignoring_accounting_into_invalid",
 "fairness_sees_real_h18_file": "test_fairness_check_sees_the_h18_bespoke_metrics_file_itself",
 "oracle_independent": "test_oracle_imports_nothing_from_engine_toolchain_or_domains",
 "oracle_import_checker_known_negative": "test_import_checker_known_negative",
 "evaluator_vs_oracle_property": "test_evaluator_agrees_with_the_independent_oracle",
 "property_reached_every_verdict": "test_zz_property_run_reached_every_verdict_class",
}
cases = {}
for tc in ET.parse(sys.argv[1]).iter("testcase"):
    base = tc.get("name").split("[")[0]
    bad = any(c.tag in ("failure", "error", "skipped") for c in tc)
    ok, n = cases.get(base, (True, 0))
    cases[base] = (ok and not bad, n + 1)
for label, name in req.items():
    ok, n = cases.get(name, (False, 0))
    print(("PASS" if ok and n else "FAIL"), f"required_test_{label}:", f"{name} ran {n} case(s), all passed" if ok and n else f"{name} missing or failing (cases={n})")
PYEOF
emit "$TMP/required.txt"

# 2. Evidence: exactly the contract's required_evidence (+ verdict.json), schema-valid, hashes intact, honest not-run content.
"$PY" - "$DIR" > "$TMP/ev.txt" 2>&1 <<'PYEOF'
import json, sys
from pathlib import Path
import jsonschema
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from eoo_exp.util import canon, sha_text
d = Path(sys.argv[1])
con = json.load(open("hypotheses/h22/contract.json"))
req = con["required_evidence"]
schema = json.load(open("schemas/evidence-record.schema.json"))
names = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
print(("PASS" if names == sorted(req + ["verdict.json"]) else "FAIL"), "evidence_files:", f"{names} vs contract {sorted(req)} + verdict.json")
bad, pay, recs = [], {}, {}
for f in [x for x in req if x.endswith(".json")]:
    try:
        r = json.load(open(d / f)); jsonschema.validate(r, schema)
        assert r["hypothesis_id"] == "H22" and r["evidence_kind"] == f[:-5] and sha_text(canon(r["payload"])) == r["payload_hash"]
        for k in ("git_commit", "protocol_freeze_hash", "engine_prereg_sha256", "seed", "input_corpus_hash", "harness_sha256", "harness_dirty", "environment", "engine_version"):
            assert k in r, k
        pay[f] = r["payload"]; recs[f] = r
    except Exception as e:
        bad.append(f"{f}: {type(e).__name__} {str(e)[:80]}")
print(("PASS" if not bad else "FAIL"), "evidence_schema_valid:", "6/6 JSON records schema-valid, payload hash intact, provenance fields present" if not bad else bad)
mf, bt, ac, cs, rt, tr = (pay[f] for f in [x for x in req if x.endswith(".json")])
manifest_real = [x["id"] for x in mf["real_domains"] if x["real"] and x["evidence_it_is_real"]]
print(("PASS" if len(manifest_real) == 2 and mf["real_domain_count"] == 2 and mf["candidate_d3_sources"] == [] and mf["synthetic_domains_counted_as_real"] == 0
       and {x["name"] for x in mf["real_domains"]} == {"manufacturing", "project"} and mf["min_real_domains_for_verdict"] == 3 else "FAIL"), "manifest_two_real_domains_no_d3:",
      f"real domains {manifest_real} ({[x['name'] for x in mf['real_domains']]}), count {mf['real_domain_count']} < 3, candidate D3 sources {mf['candidate_d3_sources']}, synthetic counted as real {mf['synthetic_domains_counted_as_real']}")
nr = {f: p.get("status") for f, p in pay.items() if f != "domain-manifest.json"}
print(("PASS" if set(nr.values()) == {"not-run"} and len(nr) == 5 and all("gate closed" in pay[f]["reason"] and "2 real domains < 3" in pay[f]["reason"] for f in nr) else "FAIL"),
      "not_run_files_honest:", f"statuses {nr}; each carries the reason 'gate closed: 2 real domains < 3 ... 0 blind tasks < 30'")
print(("PASS" if bt["tasks"] == [] and bt["tasks_completed"] == 0 and bt["reveal"] is None and ac["per_task"] == [] and cs["per_class"] == {} and tr["slope_ratio"] is None and tr["ci_low"] is None else "FAIL"),
      "no_invented_results:", f"blind tasks {len(bt['tasks'])}, per-task costs {len(ac['per_task'])}, per-class correctness rows {len(cs['per_class'])}, slope {tr['slope_ratio']}, reveal {bt['reveal']}")
c = rt["context"]
print(("PASS" if c["label"].startswith("CONTEXT, NOT TREND") and c["h18_recurring_complexity_loc"] == {"baseline": 39, "eoo": 2191} and set(c["h15_openpona_over_dsl_ratios"]) == {"manufacturing", "project"}
       and set(c["engine_toolchain_loc"]) == {"src/eoo_engine", "src/eoo_engine_git", "src/eoo_toolchain"} and rt["realistic_tier"] is None else "FAIL"), "context_facts_present_and_labelled:",
      f"H15 line ratios {{k: round(v['lines'], 3) for k, v in c['h15_openpona_over_dsl_ratios'].items()}}".replace("{k: round(v['lines'], 3) for k, v in c['h15_openpona_over_dsl_ratios'].items()}", str({k: round(v['lines'], 3) for k, v in c['h15_openpona_over_dsl_ratios'].items()}))
      + f"; H18 ratio by class {c['h18_ratio_eoo_over_baseline_by_class']}; recurring LOC {c['h18_recurring_complexity_loc']}; engine/toolchain lines {{k.split('/')[-1]: v['lines'] for k, v in c['engine_toolchain_loc'].items()}}".replace("{k.split('/')[-1]: v['lines'] for k, v in c['engine_toolchain_loc'].items()}", str({k.split('/')[-1]: v['lines'] for k, v in c['engine_toolchain_loc'].items()})))
md = (d / "tradeoff-frontier.md").read_text()
print(("PASS" if "STATUS: not-run" in md and "no weighted winner score" in md and "Context, not trend" in md else "FAIL"), "tradeoff_frontier_md:", f"{len(md.splitlines())} lines, states not-run, no winner score, context section present")
PYEOF
emit "$TMP/ev.txt"

# 3. Verdict recomputes identically from the evidence (pure function) and is INCONCLUSIVE through the domain gate.
"$PY" - "$DIR" > "$TMP/vd.txt" 2>&1 <<'PYEOF'
import json, sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from pathlib import Path
from eoo_h22.evaluate import evaluate
d = Path(sys.argv[1])
stored = json.load(open(d / "verdict.json")); fresh = evaluate(d)
same = json.dumps(stored, sort_keys=True) == json.dumps(fresh, sort_keys=True)
print(("PASS" if same else "FAIL"), "verdict_recomputes_identically:", f"stored={stored['verdict']} recomputed={fresh['verdict']} identical={same}")
print(("PASS" if fresh["verdict"] == "INCONCLUSIVE" and fresh["gate"] == {"real_domains": 2, "completed_blind_tasks": 0, "open": False} else "FAIL"), "verdict_inconclusive_via_domain_gate:", f"verdict={fresh['verdict']} gate={fresh['gate']}")
vals = {r["id"]: r["value"] for rows in fresh["predicates"].values() for r in rows}
print("PASS" if len(vals) == 11 and vals["I1"] is True and vals["R1"] is False and vals["R2"] is False and vals["V1"] is False and vals["V2"] is False else "FAIL", "verdict_all_clauses_named:", f"{len(vals)} predicates: " + " ".join(f"{k}={v}" for k, v in sorted(vals.items())))
print("PASS" if fresh["problems"] == [] and fresh["common"]["protocol_valid"] and fresh["common"]["required_evidence_complete"] and not fresh["common"]["sample_sufficient"] else "FAIL", "verdict_common:", json.dumps(fresh["common"]) + f" problems={fresh['problems']}")
PYEOF
emit "$TMP/vd.txt"

# 4. Independent probes (plain grep / hand-edited copies of the real evidence; not the harness's own builders).
imp="$(grep -nE "^(from|import) +(eoo_engine|eoo_engine_git|eoo_toolchain|domains|eoo_h22|eoo_ir|hdd|eoo_exp)" oracles/h22/*.py)"
neg="$(printf 'import os\nfrom eoo_engine import x\n' | grep -E "^(from|import) +(eoo_engine)" | wc -l | tr -d ' ')"
[ -z "$imp" ] && [ "$neg" = 1 ] && pass probe_oracle_imports_grep "oracles/h22 imports no Engine/Toolchain/domain/hdd code (grep); known-negative planted import found ($neg)" || fail probe_oracle_imports_grep "$imp neg=$neg"
"$PY" - "$DIR" "$TMP" > "$TMP/probe.txt" 2>&1 <<'PYEOF'
import hashlib, json, shutil, sys
from pathlib import Path
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from eoo_h22.evaluate import evaluate
src, tmp = Path(sys.argv[1]), Path(sys.argv[2])
def canon(x): return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
def edit(d, f, fn):
    r = json.loads((d / f).read_text()); fn(r["payload"]); r["payload_hash"] = hashlib.sha256(canon(r["payload"]).encode()).hexdigest(); (d / f).write_text(json.dumps(r))
def fresh(name):
    d = tmp / name; shutil.copytree(src, d); (d / "verdict.json").unlink(); return d
# P1: hand-made 3-domain, 30-task, supporting scenario from the real run's files.
d = fresh("pos")
C = ["source_churn", "new_relation_query", "policy_composition", "action_addition", "interface_reuse"]
edit(d, "domain-manifest.json", lambda p: p.update(real_domain_count=3, real_domains=p["real_domains"] + [{"id": "D3", "name": "x", "real": True, "evidence_it_is_real": ["fixture"]}]))
edit(d, "blind-task-results.json", lambda p: p.update(tasks=[{"task_id": f"t{i}", "domain": ["D1", "D2", "D3"][i % 3], "task_class": C[i % 5], "status": "complete"} for i in range(30)]))
edit(d, "adaptation-costs.json", lambda p: p.update(per_task=[{"task_id": f"t{i}", "eoo_cost": 60, "baseline_cost": 100, "eoo_components": {"a": 1}, "baseline_components": {"a": 1}} for i in range(30)]))
edit(d, "correctness-security.json", lambda p: p.update(per_class={c: {"non_inferior": True} for c in C}, regressions=0))
edit(d, "runtime-tax.json", lambda p: p.update(realistic_tier_gain_not_dominated_by_tax=True, fair_baseline_savings_persist=True))
edit(d, "trend-analysis.json", lambda p: p.update(slope_ratio=0.5, ci_low=0.4, ci_high=0.6))
v = evaluate(d)["verdict"]
print(("PASS" if v == "SUPPORTED" else "FAIL"), "probe_known_positive_3_domains_30_tasks:", f"hand-built 3 real domains / 30 tasks / ratio 0.60 / slope 0.5 -> {v}")
# P2: the same but the third domain missing -> INCONCLUSIVE (the gate, not the numbers, decides).
edit(d, "domain-manifest.json", lambda p: p.update(real_domains=p["real_domains"][:2], real_domain_count=3))
v2 = evaluate(d); print(("PASS" if v2["verdict"] == "INCONCLUSIVE" and v2["gate"]["open"] is False else "FAIL"), "probe_gate_decides_not_numbers:", f"identical supporting numbers, 2 real domains (stated count 3) -> {v2['verdict']}, gate open={v2['gate']['open']}")
# P3: 3 domains, every ratio 0.95 -> REJECTED.
edit(d, "domain-manifest.json", lambda p: p.update(real_domains=p["real_domains"] + [{"id": "D3", "name": "x", "real": True, "evidence_it_is_real": ["fixture"]}]))
edit(d, "adaptation-costs.json", lambda p: [t.update(eoo_cost=95) for t in p["per_task"]]); edit(d, "trend-analysis.json", lambda p: p.update(slope_ratio=0.95, ci_low=0.9, ci_high=1.0))
v3 = evaluate(d)["verdict"]; print(("PASS" if v3 == "REJECTED" else "FAIL"), "probe_known_negative_ratios_095:", f"3 domains, 30 tasks, all ratios 0.95 -> {v3}")
# P4: an ignored-glue accounting (baseline task component set to null) -> INVALID.
edit(d, "adaptation-costs.json", lambda p: p["per_task"][0]["baseline_components"].update(a=None))
v4 = evaluate(d)["verdict"]; print(("PASS" if v4 == "INVALID" else "FAIL"), "probe_ignored_glue_invalid:", f"one baseline cost component nulled -> {v4}")
# P5: fairness check over the committed H18 bespoke metrics, recomputed here by hand from the per-file assignment.
p = json.load(open("experiments/h18/exp-h18-001/bespoke-change-metrics.json"))["payload"]
a = p["assignment"]; rows = []
for cls in ("TC1", "TC2", "TC3"):
    for var in ("baseline", "eoo"):
        cfg = sum(a[var]["config"].get(cls, {}).values()); py = sum(a[var]["python"].get(cls, {}).values())
        ex = p["per_class"][cls][var].get("mandatory_extras", {"total": 0})["total"] if var == "eoo" else 0
        rows.append(p["per_class"][cls][var]["total"] == cfg + py + sum(a[var]["config"].get(cls + "X", {}).values()) + sum(a[var]["python"].get(cls + "X", {}).values()) and ex >= 0)
print(("PASS" if all(rows) and len(rows) == 6 else "FAIL"), "probe_h18_totals_recomputed_by_hand:", f"6/6 (class, variant) totals equal config+python (+extras) from the per-file assignment; recurring {p['recurring_complexity_loc']['baseline']} vs {p['recurring_complexity_loc']['eoo']}")
PYEOF
emit "$TMP/probe.txt"
big="$(wc -l src/eoo_h22/*.py oracles/h22/*.py | awk '$2 != "total" && $1 >= 250 {print $2"="$1}')"
[ -z "$big" ] && pass module_size "all eoo_h22 / oracle modules < 250 lines (max $(wc -l src/eoo_h22/*.py oracles/h22/*.py | awk '$2 != "total"' | sort -n | tail -1 | awk '{print $2"="$1}'))" || fail module_size "$big"

# 5. Runner: refuses to overwrite; a fresh run writes exactly the seven files and evaluates INCONCLUSIVE.
"$PY" scripts/run_h22.py --exp-id "$EXP" --seed "$SEED" --out-root "$R2/experiments/h22" > "$TMP/refuse.log" 2>&1
[ $? -eq 2 ] && grep -q REFUSED "$TMP/refuse.log" && pass runner_refuses_overwrite "existing $EXP dir -> exit 2 REFUSED" || fail runner_refuses_overwrite "$(tail -2 "$TMP/refuse.log")"
"$PY" scripts/run_h22.py --exp-id fresh --seed 3 --out-root "$TMP/fresh" > "$TMP/fresh.log" 2>&1
n=$(ls "$TMP/fresh/fresh" 2>/dev/null | wc -l | tr -d ' '); [ "$n" = 7 ] && [ ! -e "$TMP/fresh/.fresh.partial" ] && pass runner_fresh_run "7 evidence files, no .partial left" || fail runner_fresh_run "files=$n $(tail -2 "$TMP/fresh.log")"
"$PY" scripts/evaluate_h22.py "$TMP/fresh/fresh" --no-write > "$TMP/fresh_eval.log" 2>&1
grep -Eq '"verdict": "INCONCLUSIVE"' "$TMP/fresh_eval.log" && grep -Eq '"sample_sufficient": false' "$TMP/fresh_eval.log" && pass evaluator_cli_inconclusive "fresh run -> INCONCLUSIVE, sample_sufficient=false" || fail evaluator_cli_inconclusive "$(tail -4 "$TMP/fresh_eval.log")"
[ ! -e "$R2/experiments/h22/exp-h22-001" ] && pass no_authoritative_run_created "experiments/h22/exp-h22-001 does not exist (development run only)" || fail no_authoritative_run_created "exp-h22-001 exists"

# 6. Frozen / read-only files untouched.
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
ro="$(git status --porcelain -- protocol hypotheses domains src/eoo_engine src/eoo_engine_git src/eoo_ir src/eoo_dsl src/eoo_openpona src/eoo_exp src/eoo_toolchain src/eoo_h15 src/eoo_h16 src/eoo_h17 src/eoo_h18 src/eoo_h20 src/eoo_h21 experiments/h15 experiments/h16 experiments/h17 experiments/h18 experiments/h19 experiments/h20 experiments/h21 oracles/h16 oracles/h17 oracles/h18 oracles/h20 oracles/h21 ontology docs tests/engine tests/domains tests/h15 tests/h16 tests/h17 tests/h18 tests/h20 tests/h21 pyproject.toml)"
[ -z "$ro" ] && pass read_only_paths_untouched "git status on protocol/ hypotheses/ domains/ engine/ toolchain/ ir/dsl/openpona/exp, h15-h21 sources+tests+oracles+experiments, ontology, docs, pyproject.toml: clean" || fail read_only_paths_untouched "$ro"
new="$(git status --porcelain -u -- . | grep -vE ' round2/(src/eoo_h22|tests/h22|oracles/h22|experiments/h22|scripts/(run|evaluate|verify)_h22)' | head -5 | tr '\n' ' ')"
echo "INFO other_changes_in_tree_not_from_h22: ${new:-none}"

# 7. Whole round2 suite and pack check.
"$PY" -m pytest -q -p no:cacheprovider > "$TMP/full.log" 2>&1
rc=$?; s="$(summary "$TMP/full.log")"
if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/full.log"; then pass full_round2_suite "rc=0; $s"
else fail full_round2_suite "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/full.log" | head -5 | tr '\n' ' ')"; fi
(PATH="$R2/.venv/bin:$PATH" make check > "$TMP/check.log" 2>&1)
grep -aq "PACK OK" "$TMP/check.log" && pass make_check "$(grep -a 'PACK OK' "$TMP/check.log")" || fail make_check "$(tail -3 "$TMP/check.log" | tr '\n' ' ')"

echo "SUMMARY: $FAILS failing check(s)"
[ "$FAILS" -eq 0 ]
