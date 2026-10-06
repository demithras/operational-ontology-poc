#!/usr/bin/env bash
# Re-runs every acceptance check of the P5b (H17) spec. One line per check:
#   PASS <name>: <evidence>   |   FAIL <name>: <evidence>
# Exit status is non-zero if any check fails.  EXP=<id> picks the evidence dir (default exp-h17-001); SEED defaults to 17.
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
PY="$R2/.venv/bin/python"
TMP="$(cd "$(mktemp -d)" && pwd -P)"
EXP="${EXP:-exp-h17-001}"; SEED="${SEED:-17}"
FAILS=0
trap 'rm -rf "$TMP"' EXIT
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS + 1)); }
summary() { grep -aE '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error).* =+$|[0-9]+ (passed|failed|errors?)( |,|$)' "$1" | tail -1; }
emit() { while IFS= read -r line; do echo "$line"; case "$line" in FAIL*) FAILS=$((FAILS + 1));; esac; done < "$1"; }
cd "$R2" || exit 2
DIR="$R2/experiments/h17/$EXP"

# 1. H17 unit/property tests under both Hypothesis profiles; required tests present by name and passing.
for prof in dev ci; do
  HYPOTHESIS_PROFILE=$prof "$PY" -m pytest -q -p no:cacheprovider tests/h17 --junitxml="$TMP/h17_$prof.xml" > "$TMP/h17_$prof.log" 2>&1
  rc=$?; s="$(summary "$TMP/h17_$prof.log")"
  if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/h17_$prof.log"; then pass "h17_tests_$prof" "rc=0; $s"
  else fail "h17_tests_$prof" "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/h17_$prof.log" | head -5 | tr '\n' ' ')"; fi
done
"$PY" - "$TMP/h17_ci.xml" > "$TMP/required.txt" 2>&1 <<'PYEOF'
import sys, xml.etree.ElementTree as ET
req = {
 "evaluator_known_positive": "test_known_positive_is_supported",
 "evaluator_function_effect_rejected": "test_function_only_trace_with_effect_is_rejected",
 "evaluator_negative_action_effect_rejected": "test_negative_action_with_effect_is_rejected",
 "evaluator_agent_tamper_rejected": "test_agent_tamper_violation_is_rejected",
 "evaluator_agent_raw_write_rejected": "test_agent_raw_write_is_rejected",
 "evaluator_gate_failure_rejected": "test_gate_failure_in_state_machine_is_rejected",
 "evaluator_missing_class_inconclusive": "test_missing_domain_or_class_is_inconclusive",
 "evaluator_too_few_traces_inconclusive": "test_too_few_traces_is_inconclusive",
 "evaluator_oracle_disagreement_inconclusive": "test_oracle_disagreement_is_inconclusive",
 "evaluator_survivor_blocks_support": "test_surviving_mutant_blocks_support",
 "evaluator_invalid_oracle_imports_engine": "test_oracle_importing_the_engine_is_invalid",
 "evaluator_invalid_control": "test_dirty_mutation_control_is_invalid",
 "evaluator_invalid_protocol_hash": "test_wrong_protocol_hash_is_invalid",
 "evaluator_invalid_prereg_hash": "test_wrong_prereg_hash_is_invalid",
 "evaluator_invalid_provenance": "test_disagreeing_provenance_is_invalid",
 "evaluator_missing_evidence": "test_missing_evidence_never_supports",
 "evaluator_tampered_payload": "test_tampered_payload_never_supports",
 "evaluator_all_clauses": "test_every_contract_clause_has_a_predicate",
 "oracle_independent_static": "test_oracle_does_not_import_the_engine_or_domains",
 "oracle_import_checker_known_negative": "test_oracle_import_checker_catches_a_planted_import",
 "oracle_gate_tokens": "test_a_missing_gate_token_denies_with_zero_effects",
 "oracle_crash_points": "test_crash_points_then_recovery",
 "oracle_adapter_faults": "test_adapter_faults_and_outcome_observation",
 "scenarios_realise_tokens": "test_scenario_realises_its_declared_tokens",
 "machine_agrees_with_oracle": "test_generated_sequences_agree_with_the_oracle_on_both_domains",
 "machine_crash_points": "test_every_crash_point_recovers_exactly_once",
 "machine_known_negative_function_write": "test_known_negative_function_write_mutant_is_caught_by_the_machine",
 "machine_known_negative_gate_bypass": "test_known_negative_gate_bypass_mutant_is_caught_by_the_machine",
 "machine_unapproved_refused": "test_unapproved_execution_is_refused",
 "agents_raw_write_refused": "test_raw_write_attacks_are_refused",
 "agents_walker_known_negative": "test_reachability_walker_known_negative_flags_a_tool_that_exposes_the_store",
 "agents_tamper_controls": "test_tamper_controls_produce_no_unexpected_effect",
 "agents_tamper_measured": "test_tampered_returned_record_executes_an_effect_the_gates_denied",
 "agents_baseline": "test_baseline_single_operation_model_loses_to_the_metadata_attacks",
 "mutants_all_killed": "test_all_registered_target_mutants_are_killed_with_the_expected_signal",
 "mutation_controls_clean": "test_controls_are_clean_before_and_after",
 "mutation_noop_survives": "test_a_mutant_that_changes_nothing_would_survive",
 "audit_function_only_clean": "test_function_only_traces_leave_effect_log_and_store_identical",
 "audit_function_only_known_negative": "test_function_only_audit_known_negative_sees_a_function_that_writes",
 "audit_negative_cases_clean": "test_every_negative_case_has_zero_effects_and_the_expected_gate",
 "audit_negative_known_negative": "test_negative_audit_known_negative_sees_a_bypassed_gate",
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
import json, sys
from pathlib import Path
import jsonschema
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from eoo_exp.util import canon, sha_text
d = Path(sys.argv[1])
req = json.load(open("hypotheses/h17/contract.json"))["required_evidence"]
th = json.load(open("protocol/thresholds.json"))["H17"]
schema = json.load(open("schemas/evidence-record.schema.json"))
names = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
print(("PASS" if names == sorted(req + ["verdict.json"]) else "FAIL"), "evidence_files:", f"{names} vs contract {sorted(req)} + verdict.json")
bad, pay = [], {}
for f in req:
    try:
        r = json.load(open(d / f)); jsonschema.validate(r, schema)
        assert r["hypothesis_id"] == "H17" and r["evidence_kind"] == f[:-5] and sha_text(canon(r["payload"])) == r["payload_hash"]
        for k in ("git_commit", "protocol_freeze_hash", "engine_prereg_sha256", "seed", "input_corpus_hash", "harness_sha256", "harness_dirty", "environment"):
            assert k in r, k
        pay[f] = r["payload"]
    except Exception as e:
        bad.append(f"{f}: {type(e).__name__} {str(e)[:80]}")
print(("PASS" if not bad else "FAIL"), "evidence_schema_valid:", "4/4 records schema-valid, payload hash intact, provenance fields present" if not bad else bad)
sm = pay["state-machine-results.json"]; rows = sm["cases"]
by = {x: len({r["sha"] for r in rows if r["domain"] == x}) for x in ("manufacturing", "project")}
tot = len({r["sha"] for r in rows})
print(("PASS" if tot >= th["min_state_machine_examples"] and all(by.values()) else "FAIL"), "state_machine_unique_count:",
      f"{tot} unique traces (>= {th['min_state_machine_examples']}) by domain {by}; examples executed "
      f"{ {k: v['examples_executed'] for k, v in sm['per_domain'].items()} }; clean-run failures {sum(len(v['failures']) for v in sm['per_domain'].values())}")
need = ["read", "function_call", "propose", "approve", "deny", "retry", "crash_restart", "execute", "observe_outcome", "unauthorized", "stale_or_invalid"]
cc = {x: {c: sum(1 for r in rows if r["domain"] == x and c in r["classes"]) for c in need} for x in by}
ok = all(v >= 50 for x in cc for c, v in cc[x].items() if not (x == "project" and c in ("approve", "deny")))
print(("PASS" if ok else "FAIL"), "sequence_classes_present:", json.dumps(cc))
fa = pay["effect-log-audit.json"]["function_only_traces"]
fb = {x: len({r["sha"] for r in fa if r["domain"] == x}) for x in by}
print(("PASS" if all(v >= 1000 for v in fb.values()) and all(r["identical"] for r in fa) else "FAIL"), "function_only_audit:",
      f"{fb} function-only traces, {sum(r['function_calls'] for r in fa)} function calls, {sum(1 for r in fa if not r['identical'])} traces with any change")
na = pay["negative-action-results.json"]; neg = na["negative_cases"]
print(("PASS" if neg and all(r["zero_effects"] for r in neg) else "FAIL"), "negative_action_cases:",
      f"{len(neg)} cases, {sum(1 for r in neg if not r['zero_effects'])} with an effect; kinds {sorted({r['case'] for r in neg})}")
at = na["agent_attacks"]
rw = [r for r in at if r["category"] == "raw_write"]; tp = [r for r in at if r["category"] == "tamper" and not r["attack"].startswith("control")]
ct = [r for r in at if r["attack"].startswith("control")]
print(("PASS" if rw and not any(r["violation"] for r in rw) else "FAIL"), "agent_raw_write_attacks:", f"{len(rw)} attacks, {sum(r['violation'] for r in rw)} reached a write")
print(("PASS" if ct and not any(r["violation"] for r in ct) else "FAIL"), "agent_tamper_controls:", f"{len(ct)} controls, {sum(r['violation'] for r in ct)} produced an unexpected effect")
print("INFO", "agent_tamper_attacks:", f"{sum(r['violation'] for r in tp)}/{len(tp)} record-tampering attacks achieved an effect the gates denied: " +
      "; ".join(f"{r['domain']}/{r['attack']}={r['violation']}" for r in tp))
mu = pay["mutation-results.json"]
ok = all(m["killed_by_expected_signal"] and m["counterexample"] and m["counterexample"]["n_steps"] <= 4 for m in mu["mutants"]) and mu["controls"]["clean"] and mu["controls"]["clean_after_restore"]
print(("PASS" if ok else "FAIL"), "mutation_results:", f"{sum(m['killed_by_expected_signal'] for m in mu['mutants'])}/{len(mu['mutants'])} killed, controls clean "
      f"{mu['controls']['clean']}/{mu['controls']['clean_after_restore']}; shrunk lengths " + str({m['id'][:3]: m['counterexample']['n_steps'] for m in mu['mutants'] if m['counterexample']}))
PYEOF
emit "$TMP/ev.txt"

# 3. Verdict recomputes identically from the evidence (evaluator is a pure function).
"$PY" - "$DIR" > "$TMP/vd.txt" 2>&1 <<'PYEOF'
import json, sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from pathlib import Path
from eoo_h17.evaluate import evaluate
d = Path(sys.argv[1])
stored = json.load(open(d / "verdict.json")); fresh = evaluate(d)
same = json.dumps(stored, sort_keys=True) == json.dumps(fresh, sort_keys=True)
print(("PASS" if same else "FAIL"), "verdict_recomputes_identically:", f"stored={stored['verdict']} recomputed={fresh['verdict']} identical={same}")
vals = {r["id"]: r["value"] for rows in fresh["predicates"].values() for r in rows}
print("PASS" if fresh["problems"] == [] else "FAIL", "verdict_no_problems:", f"problems={fresh['problems']}")
print("PASS" if len(vals) == 14 else "FAIL", "verdict_all_clauses_named:", f"{len(vals)} named predicates: " + " ".join(f"{k}={v}" for k, v in sorted(vals.items())))
c = fresh["common"]
print("INFO", "verdict_common:", json.dumps(c))
PYEOF
emit "$TMP/vd.txt"

# 4. Independent probes against the REAL Engine (hand-written here, not the harness's attack/mutant code).
"$PY" - > "$TMP/probe.txt" 2>&1 <<'PYEOF'
import sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from unittest import mock
from eoo_h17.drivers import new_driver
from eoo_h17.audits import run_function_only
from eoo_engine import authority
from eoo_engine.registry import DISPATCH_TABLE

# A. the tamper finding, re-derived with direct API calls (project: DENIED request -> state flip -> recover()).
def tamper(flip):
    d = new_driver("project", "std")
    rec = d.engine.tool("viewer-1").propose_action("create_hypothesis", {"claim": "x"}, idempotency_key="v1")
    assert rec["state"] == "DENIED" and [g["gate"] for g in rec["gates"] if not g["passed"]] == ["authority"]
    if flip:
        rec["state"] = "APPROVED"
    d.engine.recover()
    return len(d.engine.effect_log), len(d.adapter.commits), d.engine.executions[rec["exec"]]["state"]
c, t = tamper(False), tamper(True)
print("PASS" if c == (0, 0, "DENIED") else "FAIL", "probe_tamper_control:", f"viewer-1 DENIED request + recover() without any edit -> effects/commits/state {c}")
print("INFO", "probe_tamper_attack:", f"same request after the agent set the RETURNED record's state to APPROVED -> effects/commits/state {t} "
      f"({'a gate-denied request executed: falsifier 2 of the contract' if t[0] else 'no effect'})")
# B. known-negative for the Function-only audit: a Function that also appends to the EffectLog must be flagged on the same trace.
steps = [("function", 0, 0, False), ("function", 1, 0, False), ("read", 2, 0, False)]
clean = [run_function_only(d, "std", steps)["identical"] for d in ("manufacturing", "project")]
orig = DISPATCH_TABLE["functions"].ops["call"]
def evil(eng, spec, **kw):
    out = orig(eng, spec, **kw)
    eng.effect_log.append({"effect_id": "x", "execution": "x", "action": "x", "operation": "w", "target": "t", "payload": {}, "response": None})
    return out
with mock.patch.dict(DISPATCH_TABLE["functions"].ops, {"call": evil}):
    dirty = [run_function_only(d, "std", steps)["identical"] for d in ("manufacturing", "project")]
print("PASS" if clean == [True, True] and dirty == [False, False] else "FAIL", "probe_function_audit_known_negative:",
      f"unpatched traces identical={clean}; with a Function that appends to the EffectLog identical={dirty}")
# C. known-negative for the denied-action zero-effect check: bypassing the authority gate makes the same request commit.
def stranger(domain, who, action, inputs):
    d = new_driver(domain, "std")
    rec = d.engine.propose(action, inputs, who, idempotency_key="u1")
    return rec["state"], len(d.engine.effect_log), d.external_count()
mi = {"source_warehouse": "WH-C", "destination_warehouse": "WH-B", "part": "PX-900", "quantity": 5}
base = [stranger("manufacturing", "stranger", "transfer_inventory", mi), stranger("project", "viewer-1", "create_hypothesis", {"claim": "x"})]
def allow(*a, **k):
    r = authority.Decision(); r.allowed = True; r.allow.append("m"); return r
with mock.patch.object(authority, "evaluate", allow):
    byp = [stranger("manufacturing", "stranger", "transfer_inventory", mi), stranger("project", "viewer-1", "create_hypothesis", {"claim": "x"})]
ok = all(b[0] == "DENIED" and b[1:] == (0, 0) for b in base) and all(b[1] == 1 and b[2] == 1 for b in byp)
print("PASS" if ok else "FAIL", "probe_gate_bypass_known_negative:", f"real Engine {base}; authority gate bypassed {byp}")
# D. Functions and Actions are different capability types at the tool surface.
d = new_driver("manufacturing", "std"); t = d.engine.tool("agent-1")
print("PASS" if sorted(dir(t)) == ["call_function", "propose_action", "request", "view"] and not any(hasattr(t.view, n) for n in ("write", "apply", "store", "approve", "execute"))
      else "FAIL", "probe_tool_surface:", f"tool={sorted(dir(t))} view={sorted(dir(t.view))}")
PYEOF
emit "$TMP/probe.txt"
imp="$(grep -nE "^(from|import) +(eoo_engine|eoo_toolchain|domains|eoo_exp|eoo_h17)" oracles/h17/*.py)"
[ -z "$imp" ] && pass oracle_independent "oracles/h17 imports no eoo_engine/eoo_toolchain/domains/eoo_h17 (grep)" || fail oracle_independent "$imp"
big="$(wc -l src/eoo_h17/*.py src/eoo_exp/*.py oracles/h17/*.py | awk '$2 != "total" && $1 >= 250 {print $2"="$1}')"
[ -z "$big" ] && pass module_size "all eoo_h17/eoo_exp/oracle modules < 250 lines (max $(wc -l src/eoo_h17/*.py src/eoo_exp/*.py oracles/h17/*.py | awk '$2 != "total"' | sort -n | tail -1 | awk '{print $2"="$1}'))" || fail module_size "$big"

# 5. Runner: refuses to overwrite; a small run writes exactly the four files; the same seed reproduces the corpus hash.
"$PY" scripts/run_h17.py --exp-id "$EXP" --seed "$SEED" --per-domain 5 --fn-traces 5 --control-examples 5 --mutant-examples 5 --out-root "$R2/experiments/h17" > "$TMP/refuse.log" 2>&1
[ $? -eq 2 ] && grep -q REFUSED "$TMP/refuse.log" && pass runner_refuses_overwrite "existing $EXP dir -> exit 2 REFUSED" || fail runner_refuses_overwrite "$(tail -2 "$TMP/refuse.log")"
SMALL="--per-domain 30 --fn-traces 20 --control-examples 15 --mutant-examples 40"
"$PY" scripts/run_h17.py --exp-id small --seed 3 $SMALL --out-root "$TMP/small" > "$TMP/small.log" 2>&1
n=$(ls "$TMP/small/small" 2>/dev/null | wc -l | tr -d ' '); [ "$n" = 4 ] && [ ! -e "$TMP/small/.small.partial" ] && pass runner_small_run "4 evidence files, no .partial left" || fail runner_small_run "files=$n $(tail -2 "$TMP/small.log")"
"$PY" scripts/evaluate_h17.py "$TMP/small/small" --no-write > "$TMP/small_eval.log" 2>&1
grep -Eq '"sample_sufficient": false' "$TMP/small_eval.log" && pass evaluator_small_sample_not_sufficient "n=30/domain run -> sample_sufficient=false (below the frozen 5,000): never SUPPORTED" || fail evaluator_small_sample_not_sufficient "$(head -8 "$TMP/small_eval.log")"
"$PY" scripts/run_h17.py --exp-id small2 --seed 3 $SMALL --out-root "$TMP/small" > "$TMP/small2.log" 2>&1
"$PY" - "$TMP/small/small" "$TMP/small/small2" > "$TMP/repro.txt" 2>&1 <<'PYEOF'
import json, sys
a, b = sys.argv[1:3]
ra = json.load(open(a + "/state-machine-results.json")); rb = json.load(open(b + "/state-machine-results.json"))
ca, cb = ra["input_corpus_hash"], rb["input_corpus_hash"]
ma = json.load(open(a + "/mutation-results.json"))["payload"]; mb = json.load(open(b + "/mutation-results.json"))["payload"]
ka = [(m["id"], m["killed_by_expected_signal"], m["counterexample"]["kind"]) for m in ma["mutants"]]
kb = [(m["id"], m["killed_by_expected_signal"], m["counterexample"]["kind"]) for m in mb["mutants"]]
print(("PASS" if ca == cb and ka == kb else "FAIL"), "rerun_reproduces:", f"same seed -> corpus_hash equal={ca == cb}, mutant kill rows equal={ka == kb}")
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
ro="$(git status --porcelain -- protocol hypotheses domains src/eoo_engine src/eoo_ir src/eoo_dsl src/eoo_openpona src/eoo_exp src/eoo_h16 src/eoo_h15 experiments/h15 experiments/h16 oracles/h16 ontology docs tests/engine tests/domains tests/h15 tests/h16 scripts/run_h16.py scripts/evaluate_h16.py scripts/verify_h16.sh)"
[ -z "$ro" ] && pass read_only_paths_untouched "git status on protocol/ hypotheses/ domains/ eoo_engine/ir/dsl/openpona/exp/h15/h16 experiments/h15,h16 oracles/h16 ontology docs tests/{engine,domains,h15,h16}: clean" || fail read_only_paths_untouched "$ro"
changed="$(git status --porcelain -u -- . | awk '{print $2}')"
bad=""
for f in $changed; do
  case "${f#round2/}" in
    src/eoo_h17/*|tests/h17/*|oracles/h17/*|scripts/run_h17.py|scripts/evaluate_h17.py|scripts/verify_h17.sh|experiments/h17/*) ;;
    *) bad="$bad $f";;
  esac
done
[ -z "$bad" ] && pass repo_scope "only new H17 paths: $(echo $changed | tr '\n' ' ' | cut -c1-300)" || fail repo_scope "unexpected:$bad"

# 7. Whole round2 suite and pack check.
"$PY" -m pytest -q -p no:cacheprovider > "$TMP/full.log" 2>&1
rc=$?; s="$(summary "$TMP/full.log")"
if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/full.log"; then pass full_round2_suite "rc=0; $s"
else fail full_round2_suite "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/full.log" | head -5 | tr '\n' ' ')"; fi
(PATH="$R2/.venv/bin:$PATH" make check > "$TMP/check.log" 2>&1)
grep -aq "PACK OK" "$TMP/check.log" && pass make_check "$(grep -a 'PACK OK' "$TMP/check.log")" || fail make_check "$(tail -3 "$TMP/check.log" | tr '\n' ' ')"

echo "SUMMARY: $FAILS failing check(s)"
[ "$FAILS" -eq 0 ]
