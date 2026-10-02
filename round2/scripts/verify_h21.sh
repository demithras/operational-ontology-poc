#!/usr/bin/env bash
# Re-runs every acceptance check of the P8 (H21) spec. One line per check:
#   PASS <name>: <evidence>   |   FAIL <name>: <evidence>
# Exit status is non-zero if any check fails.  EXP=<id> picks the evidence dir (default exp-h21-dev); SEED defaults to 21.
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
PY="$R2/.venv/bin/python"
TMP="$(cd "$(mktemp -d)" && pwd -P)"
EXP="${EXP:-exp-h21-dev}"; SEED="${SEED:-21}"
FAILS=0
trap 'rm -rf "$TMP"' EXIT
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS + 1)); }
summary() { grep -aE '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error).* =+$|[0-9]+ (passed|failed|errors?)( |,|$)' "$1" | tail -1; }
emit() { while IFS= read -r line; do echo "$line"; case "$line" in FAIL*) FAILS=$((FAILS + 1));; esac; done < "$1"; }
cd "$R2" || exit 2
DIR="$R2/experiments/h21/$EXP"

# 1. H21 unit / property tests under both Hypothesis profiles, and the named tests that carry each acceptance claim.
for prof in dev ci; do
  HYPOTHESIS_PROFILE=$prof "$PY" -m pytest -q -p no:cacheprovider tests/h21 --junitxml="$TMP/h21_$prof.xml" > "$TMP/h21_$prof.log" 2>&1
  rc=$?; s="$(summary "$TMP/h21_$prof.log")"
  if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/h21_$prof.log"; then pass "h21_tests_$prof" "rc=0; $s"
  else fail "h21_tests_$prof" "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/h21_$prof.log" | head -5 | tr '\n' ' ')"; fi
done
"$PY" - "$TMP/h21_ci.xml" > "$TMP/required.txt" 2>&1 <<'PYEOF'
import sys, xml.etree.ElementTree as ET
req = {
 "generated_surface_conforms": "test_generated_surface_conforms_to_the_ir",
 "rebuild_identical": "test_rebuild_is_byte_identical_and_only_generated_files_exist",
 "function_action_distinct": "test_function_and_action_types_are_distinct",
 "cardinality_accessors": "test_cardinality_decides_single_vs_list_accessors",
 "enum_optional_typed": "test_enum_constraints_and_optionality_are_typed",
 "conformance_known_negatives": "test_conformance_checker_known_negatives",
 "oracle_independent": "test_oracle_imports_nothing_from_engine_toolchain_or_domains",
 "toolchain_never_loads_oracle": "test_toolchain_never_imports_or_loads_the_oracle_or_engine",
 "import_checker_known_negatives": "test_import_checker_known_negatives",
 "toolchain_domain_blind": "test_toolchain_source_has_no_domain_identifiers",
 "relation_rule_semantics": "test_relation_rule_needs_the_relation_on_every_bound_warehouse",
 "delegation_semantics": "test_delegation_needs_the_rule_flag_and_an_allowed_delegator",
 "unregistered_and_fault": "test_unregistered_principal_and_selector_fault_expose_nothing",
 "surface_equals_oracle_property": "test_surface_equals_oracle_on_generated_cases",
 "case_corpus_coverage": "test_unique_cases_cover_every_capability_path",
 "differential_known_negative": "test_differential_known_negative_a_tampered_surface_is_caught",
 "live_engine_cross_check": "test_surface_oracle_and_live_engine_agree",
 "mutants_all_killed": "test_every_target_mutant_is_detected_and_controls_are_clean",
 "mutants_owned_by_checks": "test_each_mutant_is_caught_by_the_check_that_owns_it",
 "mutants_over_under": "test_overexposure_and_underexposure_are_separated",
 "mutants_crash_not_kill": "test_a_crashing_mutant_is_a_harness_error_never_a_kill",
 "adversarial_no_effects": "test_hidden_actions_are_absent_and_calls_have_no_effect",
 "adversarial_meter_known_negative": "test_effect_meter_known_negative_sees_a_forced_effect",
 "hidden_tool_absent": "test_hidden_tool_is_absent_not_refused",
 "interface_generic_tool": "test_one_generic_interface_tool_serves_every_implementer",
 "interface_hardcode_mutant": "test_hardcoded_interface_type_mutant_is_visible_in_the_source_and_the_results",
 "replication_ir_valid": "test_extended_ir_validates_and_the_gate0_file_is_not_the_extended_one",
 "replication_zero_handwritten": "test_no_handwritten_endpoint_or_tool_code_for_the_new_resources",
 "replication_scanner_known_negative": "test_endpoint_scanner_known_negative_finds_a_planted_endpoint",
 "replication_end_to_end": "test_the_new_resources_work_end_to_end_through_the_generated_surface",
 "replication_regenerated": "test_regenerated_surface_still_conforms_and_matches_the_oracle",
 "replication_logic_unbound_load_error": "test_without_the_logic_bindings_the_engine_refuses_to_load",
 "evaluator_known_positive": "test_known_positive_is_supported",
 "evaluator_small_run_not_supported": "test_the_real_small_run_is_not_supported_below_the_frozen_sample",
 "evaluator_all_clauses": "test_every_contract_clause_has_a_named_predicate",
 "evaluator_s1_r1": "test_s1_r1_a_handwritten_endpoint_is_rejected",
 "evaluator_s2": "test_s2_a_failed_conformance_check_blocks_support",
 "evaluator_s3_corpus": "test_s3_corpus_below_the_minimum_is_inconclusive",
 "evaluator_s3_duplicates": "test_s3_duplicate_case_hashes_do_not_count_as_unique",
 "evaluator_s3_r1_overexposure": "test_s3_r1_an_overexposed_capability_is_rejected",
 "evaluator_s4_r1": "test_s4_r1_a_forbidden_effect_is_rejected",
 "evaluator_s4_blind_meter": "test_s4_a_blind_effect_meter_is_inconclusive",
 "evaluator_s5": "test_s5_a_per_type_tool_blocks_support",
 "evaluator_s5_i1": "test_s5_i1_polymorphism_not_implemented_is_inconclusive",
 "evaluator_s6": "test_s6_a_surviving_mutant_blocks_support",
 "evaluator_v1_oracle_import": "test_v1_toolchain_importing_the_oracle_is_invalid",
 "evaluator_v2": "test_v2_wrong_protocol_hash_is_invalid",
 "evaluator_v3": "test_v3_disagreeing_provenance_is_invalid",
 "evaluator_v4": "test_v4_oracle_importing_the_engine_is_invalid",
 "evaluator_v5": "test_v5_unclean_mutation_controls_invalidate",
 "evaluator_missing_evidence": "test_missing_evidence_never_supports",
 "evaluator_tampered_payload": "test_tampered_payload_never_supports",
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

# 2. Evidence: exactly the contract's required_evidence (+ verdict.json), schema-valid, hashes intact, sizes as frozen.
"$PY" - "$DIR" > "$TMP/ev.txt" 2>&1 <<'PYEOF'
import json, sys
from pathlib import Path
import jsonschema
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from eoo_exp.util import canon, sha_text
d = Path(sys.argv[1])
con = json.load(open("hypotheses/h21/contract.json"))
req = con["required_evidence"]; minimum = con["experiment"]["minimum_runs"]
th = json.load(open("protocol/thresholds.json"))["H21"]
schema = json.load(open("schemas/evidence-record.schema.json"))
names = sorted(p.name for p in d.iterdir()) if d.is_dir() else []
print(("PASS" if names == sorted(req + ["verdict.json"]) else "FAIL"), "evidence_files:", f"{names} vs contract {sorted(req)} + verdict.json")
bad, pay, recs = [], {}, {}
for f in req:
    try:
        r = json.load(open(d / f)); jsonschema.validate(r, schema)
        assert r["hypothesis_id"] == "H21" and r["evidence_kind"] == f[:-5] and sha_text(canon(r["payload"])) == r["payload_hash"]
        for k in ("git_commit", "protocol_freeze_hash", "engine_prereg_sha256", "seed", "input_corpus_hash", "harness_sha256", "harness_dirty", "environment", "engine_version"):
            assert k in r, k
        pay[f] = r["payload"]; recs[f] = r
    except Exception as e:
        bad.append(f"{f}: {type(e).__name__} {str(e)[:80]}")
print(("PASS" if not bad else "FAIL"), "evidence_schema_valid:", "6/6 records schema-valid, payload hash intact, provenance fields present" if not bad else bad)
mf, hw, sec, adv, pol, mu = (pay[f] for f in req)
ev = {r["engine_version"] for r in recs.values()}
c = mf["candidate"]
print(("PASS" if ev == {"1.1"} and c["engine_tag"] == "r2-engine-v1.1" else "FAIL"), "evidence_names_engine_version:", f"ENGINE_VERSION {sorted(ev)}, tag {c['engine_tag']} -> {c['engine_tag_commit'][:12]}, run at HEAD {c['head'][:12]}")
# generated surface manifest
rows = []
for x, m in mf["domains"].items():
    cf = m["conformance"]
    rows.append(f"{x}: {m['tools']['count']} tools {m['tools']['by_kind']}, conformance {cf['passed']}/{cf['checks']}, clean_build={m['clean_build']}, rebuild_identical={m['rebuild_identical']}, stray_files={m['handwritten_files_in_generated_dir']}")
ok = all(m["clean_build"] and m["rebuild_identical"] and m["conformance"]["passed"] == m["conformance"]["checks"] > 0 and not m["handwritten_files_in_generated_dir"] for m in mf["domains"].values())
print(("PASS" if ok and set(mf["domains"]) == {"manufacturing", "project"} else "FAIL"), "manifest_clean_build_and_conformance:", "; ".join(rows))
print(("PASS" if mf["toolchain"]["imports_oracle"] is False and not mf["toolchain"]["forbidden_imports"] and not mf["domain_token_scan"]["hits"] else "FAIL"), "manifest_toolchain_static:",
      f"{len(mf['toolchain']['files'])} toolchain files, {mf['toolchain']['total_lines']} lines; imports_oracle={mf['toolchain']['imports_oracle']}, forbidden imports {mf['toolchain']['forbidden_imports']}, "
      f"{mf['domain_token_scan']['identifiers_checked']} domain identifiers checked, hits {mf['domain_token_scan']['hits']}")
# handwritten diff
e2e = hw["end_to_end"]
print(("PASS" if hw["handwritten_endpoint_or_tool_code_added"] == 0 and not hw["toolchain_files_changed"] and not hw["token_occurrences_in_toolchain_and_domains"] and hw["gate0_files_unchanged"]
       and hw["handwritten_endpoint_definitions"]["scanner_known_negative_planted_endpoint"] == ["act_register_replication"] and th["max_handwritten_endpoints_for_preregistered_ordinary_resources"] == 0 else "FAIL"),
      "handwritten_diff:", f"handwritten endpoint/tool code added {hw['handwritten_endpoint_or_tool_code_added']} (frozen max {th['max_handwritten_endpoints_for_preregistered_ordinary_resources']}); toolchain files changed {hw['toolchain_files_changed']}; "
      f"new generated tools {hw['generated_new_tools']}; new SDK symbols {hw['generated_new_sdk_symbols']}; domain logic {hw['domain_logic']['bindings']} bindings / {hw['domain_logic']['lines_total']} lines (counted separately); "
      f"scanner known-negative finds {hw['handwritten_endpoint_definitions']['scanner_known_negative_planted_endpoint']}")
print(("PASS" if e2e["all_ok"] and len(e2e["steps"]) == 5 else "FAIL"), "handwritten_diff_end_to_end:", "; ".join(f"{'ok' if s['ok'] else 'NOT OK'}: {s['step'][:70]}" for s in e2e["steps"]))
print(("PASS" if hw["regenerated_conformance"]["failed"] == 0 and hw["regenerated_differential"]["mismatching_cases"] == 0 else "FAIL"), "handwritten_diff_regenerated_surface:",
      f"extended project IR regenerated: conformance {hw['regenerated_conformance']['passed']}/{hw['regenerated_conformance']['checks']}, differential {hw['regenerated_differential']['cases']} cases, mismatches {hw['regenerated_differential']['mismatching_cases']}")
# security differential
rows, ok = [], True
for x, dd in sec["domains"].items():
    u = len(set(dd["case_sha256"])); df = dd["differential"]; ec = dd["engine_cross_check"]
    ok = ok and u >= minimum and u >= th["min_generated_principal_cases"] and df["mismatching_cases"] == 0 and df["cases"] == len(dd["case_sha256"]) and ec["disagreements"] == 0
    rows.append(f"{x}: {u} unique cases (>= {minimum}), mismatching {df['mismatching_cases']} (over {df['overexposed_total']}, under {df['underexposed_total']}), compared {df['capabilities_compared']}, "
                f"delegated {df['coverage']['delegated']}, allowed-action cases {df['coverage']['with_allowed_action']}, engine cross-check {ec['cases']} cases / {ec['decisions_compared']} decisions / {ec['disagreements']} disagreements")
print(("PASS" if ok else "FAIL"), "security_differential:", "; ".join(rows))
# adversarial
rows, ok = [], True
for x, a in adv["domains"].items():
    t = a["totals"]
    ok = ok and t["principals_with_effects"] == 0 and t["other_outcomes"] == 0 and t["engine_touched_by_surface_attacks"] == 0 and t["unknown_tool"] == t["direct_calls"] + t["fuzz_calls"] and t["backstop_calls"] == t["backstop_denied"] and a["positive_control"]["effect_observed"] and t["hidden_action_instances"] > 0
    rows.append(f"{x}: {t['principals']} principals, {t['hidden_action_instances']} hidden action instances, {t['direct_calls']} direct + {t['fuzz_calls']} fuzzed calls -> {t['unknown_tool']} UnknownTool, effects {t['principals_with_effects']}, "
                f"Engine backstop {t['backstop_denied']}/{t['backstop_calls']} denied, positive control effect_observed={a['positive_control']['effect_observed']} ({a['positive_control']['tool']})")
print(("PASS" if ok else "FAIL"), "agent_adversarial:", "; ".join(rows))
# interface polymorphism
rows, ok = [], True
for x, rr in pol["domains"].items():
    for r in rr:
        ok = ok and r["equals_store"] and not r["tool_source_names_an_implementer"] and r["after_adding_two_implementers"]["tool_source_identical"] and r["after_adding_two_implementers"]["serves_new_types"] and r["types_served"] == r["types_with_objects"]
    key = {"project": "VersionedResearchObject", "manufacturing": "Statused"}[x]
    k = next(r for r in rr if r["interface"] == key)
    ok = ok and k["implementer_count"] >= th["min_interface_implementations"]
    rows.append(f"{x}: {len(rr)} interfaces, {key} x{k['implementer_count']} implementers served {k['types_served']}, generic tool source unchanged after adding 2 implementers")
print(("PASS" if ok and pol["extended_project_ir_replication_as_seventh_implementer"]["ok"] else "FAIL"), "interface_polymorphism:", "; ".join(rows) + f"; Replication as 7th implementer ok={pol['extended_project_ir_replication_as_seventh_implementer']['ok']}")
# mutation
tg = [m for m in mu["mutants"] if m["target"]]
def killed(m):
    return not m["harness_errors"] and all(r["conformance_failed"] or r["differential_mismatching_cases"] or r["polymorphism_failures"] for r in m["per_domain"].values()) and len(m["per_domain"]) == 2
det = [m for m in tg if killed(m)]
print(("PASS" if len(det) == len(tg) >= 5 and mu["controls"]["clean"] and sum(m["contract_mutation"] for m in tg) == 5 else "FAIL"), "mutation_results:",
      f"{len(det)}/{len(tg)} killed in both domains, controls clean={mu['controls']['clean']}; " + "; ".join(f"{m['id']}:{'+'.join(m['detected_by'])}" for m in tg))
PYEOF
emit "$TMP/ev.txt"

# 3. Verdict recomputes identically from the evidence (evaluator is a pure function).
"$PY" - "$DIR" > "$TMP/vd.txt" 2>&1 <<'PYEOF'
import json, sys
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from pathlib import Path
from eoo_h21.evaluate import evaluate
d = Path(sys.argv[1])
stored = json.load(open(d / "verdict.json")); fresh = evaluate(d)
same = json.dumps(stored, sort_keys=True) == json.dumps(fresh, sort_keys=True)
print(("PASS" if same else "FAIL"), "verdict_recomputes_identically:", f"stored={stored['verdict']} recomputed={fresh['verdict']} identical={same}")
vals = {r["id"]: r["value"] for rows in fresh["predicates"].values() for r in rows}
print("PASS" if fresh["problems"] == [] else "FAIL", "verdict_no_problems:", f"problems={fresh['problems']}")
print("PASS" if len(vals) == 15 else "FAIL", "verdict_all_clauses_named:", f"{len(vals)} named predicates: " + " ".join(f"{k}={v}" for k, v in sorted(vals.items())))
print("INFO", "verdict_common:", json.dumps(fresh["common"]), "verdict =", fresh["verdict"])
PYEOF
emit "$TMP/vd.txt"

# 4. Independent probes (hand-written here: plain grep / text edits of the GENERATED files / dataclass introspection; no harness scanners).
imp="$(grep -nE "^(from|import) +(oracles|eoo_engine|eoo_engine_git|domains|eoo_h21|eoo_exp|eoo_h20)" src/eoo_toolchain/*.py)"
neg="$(printf 'import os\nfrom oracles.h21 import authority_oracle\n' | grep -E "^(from|import) +(oracles|eoo_engine)" | wc -l | tr -d ' ')"
[ -z "$imp" ] && [ "$neg" = 1 ] && pass probe_toolchain_imports_grep "no oracle/Engine/domain import line in src/eoo_toolchain/*.py (grep); known-negative planted import line found ($neg)" || fail probe_toolchain_imports_grep "$imp neg=$neg"
imp="$(grep -nE "^(from|import) +(eoo_engine|eoo_engine_git|eoo_toolchain|domains|eoo_h21|eoo_ir|hdd|eoo_exp)" oracles/h21/*.py)"
[ -z "$imp" ] && pass probe_oracle_imports_grep "oracles/h21 imports no Engine/Toolchain/domain/IR code (grep)" || fail probe_oracle_imports_grep "$imp"
tok="$(grep -rnE "Replication|REPLICATES|register_replication|count_replications" src/eoo_toolchain domains --include='*.py' | head -3)"
gd="$(git status --porcelain -- domains src/eoo_engine src/eoo_engine_git src/eoo_ir | head -3)"
h_now="$("$PY" -c "import hashlib;print(hashlib.sha256(open('domains/project/ir.json','rb').read()).hexdigest())")"
h_head="$(git show HEAD:round2/domains/project/ir.json | "$PY" -c "import hashlib,sys;print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())")"
[ -z "$tok" ] && [ -z "$gd" ] && [ "$h_now" = "$h_head" ] && pass probe_zero_handwritten_for_new_resources "grep of the four resource names in src/eoo_toolchain + domains: no hit; git status on domains/ Engine/ IR: clean; Gate-0 ir.json sha256 == HEAD blob (${h_now:0:12})" || fail probe_zero_handwritten_for_new_resources "tok=$tok git=$gd $h_now vs $h_head"
"$PY" - > "$TMP/probe2.txt" 2>&1 <<'PYEOF'
import dataclasses, json, re, sys, tempfile
from pathlib import Path
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from domains._pack import boot, load_ir
from domains.project.pack import build_pack
from eoo_toolchain import build, load_generated
from eoo_toolchain.runtime import EngineClient, UnknownTool
ir = load_ir("project")
d = tempfile.mkdtemp(); inv = build(ir, d)
sdk, caps, surf = load_generated(d, inv["package"])
# P3: dataclass fields / callable classes straight from the IR
bad = [o["id"] for o in ir["object_types"] if [f.name for f in dataclasses.fields(getattr(sdk, o["id"]))] != [p["name"] for p in sorted(o["properties"], key=lambda p: not p.get("required"))]]
nf = sum(1 for n in dir(sdk) if n.startswith("Fn_")); na = sum(1 for n in dir(sdk) if n.startswith("Act_"))
print("PASS" if not bad and nf == len(ir["functions"]) and na == len(ir["actions"]) else "FAIL", "probe_sdk_shape_from_ir:",
      f"{len(ir['object_types'])} object classes with exactly the IR properties (mismatches {bad}); {nf} Fn_ classes == {len(ir['functions'])} IR functions; {na} Act_ classes == {len(ir['actions'])} IR actions")
# P2: hand-built world, hand-built principals; unedited generated surface vs a TEXT-EDITED generated caps.py
objs = {o["id"]: [f"{o['id']}-0"] for o in ir["object_types"]}
from eoo_toolchain.runtime import World
def acts(surf_mod, roles):
    s = surf_mod.AgentSurface(None, {"pid": "x", "roles": roles, "relations": [], "delegated_by": None}, World(objs, {"preregistered": []}),
                              {"ProjectOntology:*": lambda c: True, "Threshold:preregistered": lambda c: False})
    return sorted(t for t in s.tools if t.startswith("act_"))
clean_r, clean_v = acts(surf, ["researcher"]), acts(surf, [])
print("PASS" if len(clean_r) == 10 and clean_v == [] else "FAIL", "probe_unedited_surface:", f"researcher gets {len(clean_r)} action tools, a principal with no role gets {clean_v}")
p = Path(d) / inv["package"] / "caps.py"; text = p.read_text()
edited = text.replace("'principal': ['role', 'researcher']", "'principal': ['any']")
assert edited != text, "edit did not apply"
p.write_text(edited)
sdk2, caps2, surf2 = load_generated(d, inv["package"])
over = acts(surf2, [])
print("PASS" if len(over) == 10 else "FAIL", "probe_text_edited_generated_caps_overexposes:", f"known-negative: editing the generated caps.py (role:researcher -> any) makes a role-less principal see {len(over)} action tools (control above: 0)")
p.write_text(text)
s2 = Path(d) / inv["package"] / "sdk.py"; t2 = s2.read_text()
e2 = re.sub(r"\n    claim: str\n", "\n", t2, count=1)
assert e2 != t2
s2.write_text(e2)
sdk3, _c, _s = load_generated(d, inv["package"])
names = [f.name for f in dataclasses.fields(sdk3.Hypothesis)]
print("PASS" if "claim" not in names else "FAIL", "probe_text_edited_generated_sdk_drops_property:", f"known-negative: deleting the claim line of the generated sdk.py leaves Hypothesis fields {names}; probe_sdk_shape_from_ir would flag it")
s2.write_text(t2)
# P6: live Engine, viewer-1 asks for a hidden action by its real tool name
eng = boot("project", build_pack()); c = EngineClient(eng)
w = c.world([o["id"] for o in ir["object_types"]])
ops = {k: eng.bindings.get(kind, k) for kind, k in eng.bindings.keys() if kind in ("resource_selector", "principal_selector")}
sdk4, caps4, surf4 = load_generated(d, inv["package"])
v = surf4.AgentSurface(c, c.principal_plain("viewer-1"), w, ops)
n0, h0 = len(eng.effect_log.entries()), eng.state().state_hash()
try:
    v.call("act_create_hypothesis", claim="x", idempotency_key="probe"); outcome = "returned"
except UnknownTool:
    outcome = "UnknownTool"
unchanged = len(eng.effect_log.entries()) == n0 and eng.state().state_hash() == h0
ok = outcome == "UnknownTool" and unchanged and not any(t.startswith("act_") for t in v.tools)
r = surf4.AgentSurface(c, c.principal_plain("researcher-1"), w, ops).call("act_create_hypothesis", claim="probe positive", idempotency_key="probe-2")
print("PASS" if ok and r["state"] == "RECONCILED_SUCCESS" and len(eng.effect_log.entries()) > n0 else "FAIL", "probe_live_viewer_vs_researcher:",
      f"viewer-1 act_create_hypothesis -> {outcome}, effects and canonical state unchanged={unchanged}; researcher-1 same tool -> {r['state']} (effects now {len(eng.effect_log.entries())})")
PYEOF
emit "$TMP/probe2.txt"
"$PY" - > "$TMP/probe3.txt" 2>&1 <<'PYEOF'
import sys, tempfile
sys.path.insert(0, "src"); sys.path.insert(0, ".")
from domains._pack import load_ir
from eoo_h21 import cases, differential
from eoo_toolchain import build, load_generated
rows = []
for dom in ("manufacturing", "project"):
    ir = load_ir(dom); d = tempfile.mkdtemp(); inv = build(ir, d); _s, _c, surf = load_generated(d, inv["package"])
    cs = cases.unique_cases(ir, 600, 4242)
    r = differential.run(ir, surf, cs)
    rows.append((dom, len(cs), r["mismatching_cases"], r["coverage"]["with_allowed_action"]))
print("PASS" if all(m == 0 and n == 600 and a > 0 for _d, n, m, a in rows) else "FAIL", "probe_fresh_seed_differential:",
      "seed 4242 (not the run's seed): " + "; ".join(f"{d}: {n} unique cases, mismatches {m}, cases with an allowed action {a}" for d, n, m, a in rows))
PYEOF
emit "$TMP/probe3.txt"
big="$(wc -l src/eoo_h21/*.py src/eoo_toolchain/*.py oracles/h21/*.py | awk '$2 != "total" && $1 >= 250 {print $2"="$1}')"
[ -z "$big" ] && pass module_size "all eoo_h21 / eoo_toolchain / oracle modules < 250 lines (max $(wc -l src/eoo_h21/*.py src/eoo_toolchain/*.py oracles/h21/*.py | awk '$2 != "total"' | sort -n | tail -1 | awk '{print $2"="$1}'))" || fail module_size "$big"

# 5. Runner: refuses to overwrite; a small run writes exactly the six files and is never SUPPORTED below the frozen sample.
"$PY" scripts/run_h21.py --exp-id "$EXP" --seed "$SEED" --out-root "$R2/experiments/h21" > "$TMP/refuse.log" 2>&1
[ $? -eq 2 ] && grep -q REFUSED "$TMP/refuse.log" && pass runner_refuses_overwrite "existing $EXP dir -> exit 2 REFUSED" || fail runner_refuses_overwrite "$(tail -2 "$TMP/refuse.log")"
"$PY" scripts/run_h21.py --exp-id small --seed 3 --n-cases 200 --n-engine 50 --n-mutant-cases 100 --n-fuzz 10 --out-root "$TMP/small" > "$TMP/small.log" 2>&1
n=$(ls "$TMP/small/small" 2>/dev/null | wc -l | tr -d ' '); [ "$n" = 6 ] && [ ! -e "$TMP/small/.small.partial" ] && pass runner_small_run "6 evidence files, no .partial left" || fail runner_small_run "files=$n $(tail -2 "$TMP/small.log")"
"$PY" scripts/evaluate_h21.py "$TMP/small/small" --no-write > "$TMP/small_eval.log" 2>&1
grep -Eq '"sample_sufficient": false' "$TMP/small_eval.log" && grep -Eq '"verdict": "INCONCLUSIVE"' "$TMP/small_eval.log" && pass evaluator_small_sample_not_supported "200-case run -> sample_sufficient=false, INCONCLUSIVE (frozen minimum 10,000)" || fail evaluator_small_sample_not_supported "$(head -8 "$TMP/small_eval.log")"

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
ro="$(git status --porcelain -- protocol hypotheses domains src/eoo_engine src/eoo_engine_git src/eoo_ir src/eoo_dsl src/eoo_openpona src/eoo_exp src/eoo_h15 src/eoo_h16 src/eoo_h17 src/eoo_h18 src/eoo_h20 experiments/h15 experiments/h16 experiments/h17 experiments/h18 experiments/h19 experiments/h20 oracles/h16 oracles/h17 oracles/h18 oracles/h20 ontology docs tests/engine tests/domains tests/h15 tests/h16 tests/h17 tests/h18 tests/h20 pyproject.toml)"
[ -z "$ro" ] && pass read_only_paths_untouched "git status on protocol/ hypotheses/ domains/ eoo_engine/ eoo_engine_git/ ir/dsl/openpona/exp/h15-h18/h20 experiments/h15-h20 oracles/h16-h20 ontology docs tests/{engine,domains,h15-h18,h20} pyproject.toml: clean" || fail read_only_paths_untouched "$ro"
changed="$(git status --porcelain -u -- . | awk '{print $2}')"
bad=""
for f in $changed; do
  case "${f#round2/}" in
    src/eoo_h21/*|src/eoo_toolchain/*|tests/h21/*|oracles/h21/*|scripts/run_h21.py|scripts/evaluate_h21.py|scripts/verify_h21.sh|experiments/h21/*) ;;
    *) bad="$bad $f";;
  esac
done
[ -z "$bad" ] && pass repo_scope "only new H21 paths (eoo_h21, eoo_toolchain, oracles/h21, tests/h21, run/evaluate/verify scripts, experiments/h21): $(echo $changed | tr '\n' ' ' | cut -c1-300)" || fail repo_scope "unexpected:$bad"

# 7. Whole round2 suite and pack check.
"$PY" -m pytest -q -p no:cacheprovider > "$TMP/full.log" 2>&1
rc=$?; s="$(summary "$TMP/full.log")"
if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/full.log"; then pass full_round2_suite "rc=0; $s"
else fail full_round2_suite "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/full.log" | head -5 | tr '\n' ' ')"; fi
(PATH="$R2/.venv/bin:$PATH" make check > "$TMP/check.log" 2>&1)
grep -aq "PACK OK" "$TMP/check.log" && pass make_check "$(grep -a 'PACK OK' "$TMP/check.log")" || fail make_check "$(tail -3 "$TMP/check.log" | tr '\n' ' ')"

echo "SUMMARY: $FAILS failing check(s)"
[ "$FAILS" -eq 0 ]
