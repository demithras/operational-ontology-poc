#!/usr/bin/env bash
# Re-runs every acceptance check of the P4b domain-bindings spec. One line per check:
#   PASS <name>: <evidence>   |   FAIL <name>: <evidence>
# Exit status is non-zero if any check fails. Read-only on the repository (temp files only).
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
PY="$R2/.venv/bin/python"
TMP="$(cd "$(mktemp -d)" && pwd -P)"
FAILS=0
trap 'rm -rf "$TMP"' EXIT
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS + 1)); }
summary() { grep -aE '^[0-9]+ (passed|failed)|[0-9]+ (passed|failed|errors?)( |,|$)' "$1" | tail -1; }
cd "$R2" || exit 2
GIT_BEFORE="$(git status --porcelain)"

# 1. Domain tests (dev profile then derandomized ci profile) + required tests by name.
for prof in dev ci; do
  HYPOTHESIS_PROFILE=$prof "$PY" -m pytest -q -p no:cacheprovider tests/domains --junitxml="$TMP/dom_$prof.xml" > "$TMP/dom_$prof.log" 2>&1
  rc=$?
  if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/dom_$prof.log"; then pass "domain_tests_$prof" "rc=0; $(summary "$TMP/dom_$prof.log")"
  else fail "domain_tests_$prof" "rc=$rc; $(summary "$TMP/dom_$prof.log"); $(grep -aE '^FAILED' "$TMP/dom_$prof.log" | head -5 | tr '\n' ' ')"; fi
done
"$PY" - "$TMP/dom_ci.xml" > "$TMP/required.txt" 2>&1 <<'PYEOF'
import sys, xml.etree.ElementTree as ET
req = {
 "mfg_risk_function": "test_risk_function_canonical_incident",
 "mfg_transfer_allowed": "test_transfer_allowed_executes_and_reconciles",
 "mfg_junior_over_threshold_approved": "test_junior_over_threshold_requires_approval_then_senior_approves",
 "mfg_high_priority_protection": "test_high_priority_protection_denies_junior_but_not_planner",
 "mfg_protection_control": "test_protection_control_same_route_not_high_priority_junior_allowed",
 "mfg_idempotent_retry": "test_idempotent_retry_same_result_one_effect",
 "mfg_commit_without_response": "test_commit_without_response_is_outcome_unknown_then_reconciles",
 "mfg_negative_zero_effects": "test_negative_paths_have_zero_effects",
 "mfg_matches_v1_sources": "test_risk_matches_reference_model_on_seed_and_after_delay_recovery",
 "prj_preregister": "test_preregister_complete_contract_writes_git_and_projection",
 "prj_preregister_incomplete": "test_preregister_incomplete_contract_denied_zero_effects",
 "prj_threshold_after_prereg": "test_edit_threshold_after_preregistration_denied_zero_effects",
 "prj_start_without_freeze": "test_start_run_without_freeze_hash_denied_zero_effects",
 "prj_attach_without_pin": "test_attach_evidence_without_pin_denied_zero_effects",
 "prj_verdict_by_function": "test_evaluate_derives_the_verdict_by_function_not_by_input",
 "prj_verdict_not_input": "test_a_verdict_cannot_be_supplied_as_input",
 "prj_tampered_evidence": "test_tampered_evidence_hash_gives_invalid_verdict",
 "prj_supersede": "test_supersede_evaluated_hypothesis_links_successor_and_orphans_components",
 "prj_freeze_hash_reproduces": "test_compute_freeze_hash_reproduces_scripts_freeze_protocol_py",
 "prj_v1_finding_pinned": "test_FINDING_attach_evidence_does_not_create_the_link_evidence_count_reads",
 "prj_v2_lifecycle_verdict": "test_v2_attach_evidence_creates_the_link_so_a_lifecycle_verdict_is_possible",
 "prj_v2_negative_control": "test_v2_negative_control_evaluate_without_attached_evidence_cannot_support_or_reject",
 "bindings_zero_unbound": "test_zero_unbound_references",
 "bindings_no_stub_no_dead": "test_every_binding_is_used_by_the_ir_and_none_is_a_constant",
 "bindings_checker_negative": "test_checker_known_negatives",
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
while IFS= read -r line; do echo "$line"; case "$line" in FAIL*) FAILS=$((FAILS + 1));; esac; done < "$TMP/required.txt"

# 2. Binding coverage printed independently of pytest: required vs bound, per domain, via the Engine's own list.
"$PY" - > "$TMP/cov.txt" 2>&1 <<'PYEOF'
import sys
from collections import Counter
sys.path.insert(0, ".")
from eoo_engine import AdapterRegistry, required_bindings
from domains._pack import boot, load_ir
from domains.manufacturing.pack import build_pack as m
from domains.project.pack import build_pack as p
for name, mk in (("manufacturing", m), ("project", p)):
    pack = mk()
    reg = AdapterRegistry(pack[1])
    req = required_bindings(load_ir(name))
    un = [str(u) for u in req if (u.kind == "adapter" and reg.lookup(*u.key.split(":", 1)) is None)
          or (u.kind != "adapter" and not pack[0].has(u.kind, u.key))]
    boot(name, mk())
    kinds = dict(sorted(Counter(u.kind for u in req).items()))
    print(("PASS" if not un and req else "FAIL"), f"unbound_refs_{name}:", f"{len(req)} required {kinds}; unbound={un[:3]}")
PYEOF
while IFS= read -r line; do echo "$line"; case "$line" in FAIL*) FAILS=$((FAILS + 1));; esac; done < "$TMP/cov.txt"

# 3. Dry runs on the real packs: the canonical scenarios, with API reads and the printed evidence.
"$PY" - > "$TMP/dry.txt" 2>&1 <<'PYEOF'
import sys
sys.path.insert(0, "."); sys.path.insert(0, "tests/domains")
from mfg_helpers import make as mk_m, propose_transfer
risk = mk_m()[0].call_function("work_order_risk", {"work_order": "WO-42"})
print("PASS" if risk["at_risk"] and risk["shortage"] == 60 else "FAIL", "dry_mfg_risk_function:", dict(risk))
e, wms, _ = mk_m()
r = propose_transfer(e, who="junior-1", quantity=100, key="j1")
ok1 = r["state"] == "PENDING_APPROVAL"
r = e.approve(r["exec"], "senior-1")
print("PASS" if ok1 and r["state"] == "RECONCILED_SUCCESS" and wms.stock[("PX-900", "WH-B")] == 110 else "FAIL",
      "dry_mfg_junior_over_threshold_to_reconciled:", f"state={r['state']} stock WH-B={wms.stock[('PX-900', 'WH-B')]} history={r['history']}")
e, wms, _ = mk_m()
wms.mode = "commit_no_response"
r = propose_transfer(e); x = r["exec"]; s1 = r["state"]
wms.cdc_visible = False
s2 = e.reconcile(x)["state"]
wms.cdc_visible = True
s3 = e.reconcile(x)["state"]
print("PASS" if (s1, s2, s3) == ("OUTCOME_UNKNOWN", "OUTCOME_UNKNOWN", "RECONCILED_SUCCESS") and len(wms.calls) == 1 else "FAIL",
      "dry_mfg_commit_without_response:", f"{s1} -> (cdc lag) {s2} -> {s3} wms_calls={len(wms.calls)}")
from prj_helpers import make as mk_p, next_engine, EVIDENCE_002
e, git, _, sd = mk_p("RUNNING")
sts = [e.propose("attach_evidence", {"hypothesis": "H15", "evidence": ev}, "researcher-1", idempotency_key=f"a{i}")["state"] for i, ev in enumerate(EVIDENCE_002)]
e2 = next_engine(sd, git)
v = e2.call_function("derive_verdict", {"hypothesis": "H15"})
r = e2.propose("evaluate_hypothesis", {"hypothesis": "H15"}, "researcher-1", idempotency_key="ev")
vrow = next(c["row"] for c in git.commits if c["target"] == "Verdict")
print("PASS" if set(sts) == {"RECONCILED_SUCCESS"} and r["state"] == "RECONCILED_SUCCESS" and v == vrow["value"] == "SUPPORTED" else "FAIL",
      "dry_prj_h15_replay_attach_evaluate:", f"attach={sts[0]}x{len(sts)} derive_verdict={v} git_verdict={vrow['value']} evaluate={r['state']}")
e3 = next_engine(sd, git)
r = e3.propose("supersede_hypothesis", {"hypothesis": "H15", "successor": "H16"}, "researcher-1", idempotency_key="s")
e4 = next_engine(sd, git)
print("PASS" if r["state"] == "RECONCILED_SUCCESS" and e4.get("Hypothesis", "H15")["props"]["phase"] == "SUPERSEDED" else "FAIL",
      "dry_prj_supersede:", f"{r['state']} phase={e4.get('Hypothesis', 'H15')['props']['phase']} orphans={sorted(e4.call_function('find_orphan_components', {}))}")
PYEOF
while IFS= read -r line; do echo "$line"; case "$line" in FAIL*) FAILS=$((FAILS + 1));; esac; done < "$TMP/dry.txt"
grep -aqE '^(PASS|FAIL) ' "$TMP/dry.txt" || { fail dry_runs "no result lines: $(tail -3 "$TMP/dry.txt" | tr '\n' ' ')"; }

# 4. Read-only guarantees: protected paths untouched; the seed builder wrote nothing and is deterministic.
prot="$(git status --porcelain -- src/eoo_engine src/eoo_ir src/eoo_dsl src/eoo_openpona src/eoo_h15 src/hdd experiments protocol hypotheses \
  domains/manufacturing/ir.json domains/project/ir.json domains/manufacturing/dsl.yaml domains/project/dsl.yaml ontology schemas)"
[ -z "$prot" ] && pass protected_paths_untouched "git status --porcelain on engine/IR/protocol/hypotheses/experiments: empty" || fail protected_paths_untouched "$prot"
"$PY" - > "$TMP/v2.txt" 2>&1 <<'PYEOF'
import json, sys
sys.path.insert(0, ".")
from eoo_ir import validate
v1 = json.load(open("domains/project/ir.json")); v2 = json.load(open("domains/project/ir.v2.json"))
errs = validate(v2)
exp = json.loads(json.dumps(v1)); exp["version"] = "v2"
for a in exp["actions"]:
    if a["id"] == "attach_evidence":
        a["effects"].append({"target": "SUPPORTS_OR_REFUTES", "operation": "git_change"}); a["version"] = "v2"
print("PASS" if not errs and v2 == exp else "FAIL", "ir_v2_is_v1_plus_exactly_the_declared_changes:",
      f"validate errors={len(errs)}; equal to v1+3 changes={v2 == exp}")
PYEOF
while IFS= read -r line; do echo "$line"; case "$line" in FAIL*) FAILS=$((FAILS + 1));; esac; done < "$TMP/v2.txt"
[ -s domains/project/CHANGES_v2.md ] && pass changes_v2_documented "domains/project/CHANGES_v2.md $(wc -l < domains/project/CHANGES_v2.md) lines" || fail changes_v2_documented "missing"
[ -z "$(git status --porcelain -- domains/project/ir.json)" ] && pass ir_v1_byte_identical "git status on domains/project/ir.json: empty" || fail ir_v1_byte_identical "modified"
h1="$("$PY" -c 'import sys,json; sys.path.insert(0,"."); from domains.project.seed_from_repo import build_seed; import hashlib; print(hashlib.sha256(json.dumps(build_seed(),sort_keys=True).encode()).hexdigest()[:16])')"
h2="$("$PY" -c 'import sys,json; sys.path.insert(0,"."); from domains.project.seed_from_repo import build_seed; import hashlib; print(hashlib.sha256(json.dumps(build_seed(),sort_keys=True).encode()).hexdigest()[:16])')"
GIT_AFTER="$(git status --porcelain)"
[ -n "$h1" ] && [ "$h1" = "$h2" ] && [ "$GIT_BEFORE" = "$GIT_AFTER" ] && pass seed_from_repo_readonly_deterministic "two builds hash $h1; git status unchanged" \
  || fail seed_from_repo_readonly_deterministic "h1=$h1 h2=$h2 status_changed=$([ "$GIT_BEFORE" = "$GIT_AFTER" ] && echo no || echo yes)"
m1="$(shasum -a 256 domains/manufacturing/seed.json | cut -c1-16)"
"$PY" scripts/build_mfg_seed.py > /dev/null 2>&1
m2="$(shasum -a 256 domains/manufacturing/seed.json | cut -c1-16)"
[ "$m1" = "$m2" ] && pass mfg_seed_matches_generator "seed.json sha $m1 == regenerated by scripts/build_mfg_seed.py" || fail mfg_seed_matches_generator "$m1 vs $m2"
dom="$(grep -n "domains\|eoo_h15\|manufacturing\|project" src/eoo_engine/*.py | grep -v '^.*:\s*#' | head -3)"
[ -z "$dom" ] && pass engine_still_domain_blind "grep domains/manufacturing/project in src/eoo_engine: 0 hits" || fail engine_still_domain_blind "$dom"

# 5. Module size (< 250 lines) and no constant/default stubs by grep (the bytecode check is in the tests).
big="$(wc -l domains/*.py domains/*/*.py domains/*/logic/*.py domains/*/adapters/*.py tests/domains/*.py | awk '$2 != "total" && $1 >= 250 {print $2"="$1}')"
[ -z "$big" ] && pass module_size_lt_250 "max $(wc -l domains/*/logic/*.py domains/*/adapters/*.py domains/*.py domains/*/*.py tests/domains/*.py | awk '$2 != "total"' | sort -n | tail -1 | awk '{print $2"="$1}')" || fail module_size_lt_250 "$big"
stub="$(grep -nE 'lambda [a-z_, ]*: *(True|False|None)\b|^\s*return (True|False)\s*#\s*(stub|todo)' domains/*/logic/*.py | head -3)"
[ -z "$stub" ] && pass no_constant_stub_lambdas "grep for constant lambdas in domains/*/logic: 0 hits" || fail no_constant_stub_lambdas "$stub"

# 6. Meta-tests: each injected defect (module attribute patched in-process) must turn its named test red; the control
#    (no patch) is green. The repository files are never modified.
cat > "$TMP/mut.py" <<'PYEOF'
import sys, importlib
sys.path.insert(0, "."); sys.path.insert(0, "tests/domains")
import pytest
spec = sys.argv[1]
if spec != "control":
    mod, attr, expr = spec.split("|")
    m = importlib.import_module(mod)
    assert hasattr(m, attr), (mod, attr)
    class V:  # stands in for a Verdict enum member
        value = "SUPPORTED"
    setattr(m, attr, eval(expr, {"V": V}))
sys.exit(pytest.main(["-q", "-p", "no:cacheprovider", "--no-header", "tests/domains", "-k", "not coverage"]))
PYEOF
mutant() {  # $1 label, $2 "module|attr|expr", $3 expected failing test
  "$PY" "$TMP/mut.py" "$2" > "$TMP/mut_$1.log" 2>&1
  rc=$?
  if [ "$1" = control ]; then
    [ $rc -eq 0 ] && pass mutant_control "unpatched run green: $(summary "$TMP/mut_$1.log")" || fail mutant_control "rc=$rc $(summary "$TMP/mut_$1.log")"
  elif [ $rc -ne 0 ] && grep -aq "^FAILED.*$3" "$TMP/mut_$1.log"; then
    pass "mutant_$1" "killed by $3; $(summary "$TMP/mut_$1.log")"
  else
    fail "mutant_$1" "survived or wrong kill (rc=$rc) $(summary "$TMP/mut_$1.log")"
  fi
}
mutant control control x
mutant mfg_protection_off "domains.manufacturing.logic.policies|_protection_denies|lambda c: False" test_high_priority_protection_denies_junior_but_not_planner
mutant mfg_threshold_off "domains.manufacturing.logic.data|APPROVAL_THRESHOLD_UNITS|10**6" test_junior_over_threshold_requires_approval_then_senior_approves
mutant mfg_freshness_off "domains.manufacturing.logic.facts|freshness|lambda v, now: 'FRESH'" test_negative_paths_have_zero_effects
mutant prj_threshold_policy_off "domains.project.logic.policies|_threshold_edit_denied|lambda c: False" test_edit_threshold_after_preregistration_denied_zero_effects
mutant prj_freeze_policy_off "domains.project.logic.policies|_running_without_freeze|lambda c: False" test_start_run_without_freeze_hash_denied_zero_effects
mutant prj_pin_check_off "domains.project.logic.actions|evidence_pinned|lambda *a: True" test_attach_evidence_without_pin_denied_zero_effects
mutant prj_completeness_off "domains.project.logic.policies|contract_complete|lambda *a, **k: True" test_preregister_incomplete_contract_denied_zero_effects
mutant prj_verdict_always_supported "domains.project.logic.derive|evaluate_common|lambda x: V()" test_missing_evidence_gives_inconclusive_never_supported
mutant prj_lifecycle_guard_off "domains.project.logic.policies|legal_transition|lambda a, b: True" test_lifecycle_order_policy_alone_denies_an_illegal_transition
mutant prj_freeze_digest_wrong "domains.project.logic.freeze|freeze_digest|lambda e: '0'" test_compute_freeze_hash_reproduces_scripts_freeze_protocol_py

# 7. Whole round2 suite + make check.
# full suite under the DEFAULT dev profile (the previously flaky engine test is now derandomized on its own)
env -u HYPOTHESIS_PROFILE "$PY" -m pytest -q -p no:cacheprovider > "$TMP/all.log" 2>&1
rc=$?
s="$(summary "$TMP/all.log")"
if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/all.log"; then pass round2_full_suite "rc=0; $s"; else fail round2_full_suite "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/all.log" | head -5 | tr '\n' ' ')"; fi
"$PY" scripts/check_pack.py > "$TMP/pack.log" 2>&1
grep -aq "PACK OK" "$TMP/pack.log" && pass make_check "$(grep -a 'PACK OK' "$TMP/pack.log" | tail -1)" || fail make_check "$(tail -2 "$TMP/pack.log" | tr '\n' ' ')"

echo "---"
[ $FAILS -eq 0 ] && echo "ALL CHECKS PASSED" || echo "$FAILS CHECK(S) FAILED"
[ $FAILS -eq 0 ]
