#!/usr/bin/env bash
# Re-runs every acceptance check of the P4a Engine-core spec. One line per check:
#   PASS <name>: <evidence>   |   FAIL <name>: <evidence>
# Exit status is non-zero if any check fails.
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
PY="$R2/.venv/bin/python"
TMP="$(cd "$(mktemp -d)" && pwd -P)"  # resolved: /var -> /private/var on macOS
FAILS=0
trap 'rm -rf "$TMP"' EXIT
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS + 1)); }
summary() { grep -aE '^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error).* =+$|[0-9]+ (passed|failed|errors?)( |,|$)' "$1" | tail -1; }

cd "$R2" || exit 2

# 1-2. Engine unit/property tests (dev profile, then derandomized ci profile), required tests by name.
for prof in dev ci; do
  HYPOTHESIS_PROFILE=$prof "$PY" -m pytest -q -p no:cacheprovider tests/engine --junitxml="$TMP/engine_$prof.xml" \
    > "$TMP/engine_$prof.log" 2>&1
  rc=$?
  s="$(summary "$TMP/engine_$prof.log")"
  if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/engine_$prof.log"; then pass "engine_tests_$prof" "rc=0; $s"
  else fail "engine_tests_$prof" "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/engine_$prof.log" | head -5 | tr '\n' ' ')"; fi
done

"$PY" - "$TMP/engine_ci.xml" > "$TMP/required.txt" 2>&1 <<'PYEOF'
import sys, xml.etree.ElementTree as ET
req = {
 "allowed": "test_allowed_path_commits_one_effect_with_provenance",
 "authority_denied": "test_authority_denied_no_rule",
 "deny_overrides_allow": "test_deny_rule_overrides_allow",
 "identity_denied": "test_identity_unknown_or_forged",
 "policy_denied": "test_policy_denied",
 "default_deny": "test_default_deny_when_no_allow_policy_applies",
 "approval_approved": "test_require_approval_then_approved",
 "approval_rejected": "test_require_approval_then_rejected",
 "second_principal": "test_approval_needs_second_principal_with_capability",
 "precondition_failed": "test_precondition_failed",
 "hard_constraint_blocked": "test_hard_constraint_blocks_before_commit",
 "idempotent_retry": "test_idempotent_retry_same_result_no_second_effect",
 "crash_after_executing": "test_crash_after_executing_then_recover_exactly_once",
 "crash_after_effects_committed": "test_crash_after_effects_committed_then_recover",
 "recovery_deterministic": "test_recovery_is_deterministic",
 "outcome_unknown": "test_outcome_unknown_then_reconciled_later",
 "reconciliation_failure": "test_reconciliation_failure",
 "function_cannot_write": "test_function_that_tries_to_write_fails_and_writes_nothing",
 "read_view_no_write_path": "test_read_view_has_no_write_path",
 "grant_required": "test_store_rejects_writes_without_valid_live_grant",
 "tool_capabilities": "test_tool_can_only_call_functions_or_propose",
 "static_domain_blind": "test_no_domain_identifier_appears_as_a_core_string_literal",
 "no_domains_import": "test_core_never_imports_or_reads_domains",
 "property_generated_random": "test_generated_packages_random_bindings",
 "property_generated_permissive": "test_generated_packages_permissive_bindings_reach_success",
 "dispatch_table_only": "test_dispatch_only_via_dispatch_table",
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

# 3. Dispatch table = the preregistered kernel kinds; every core module < 250 lines; no 'domains' in core.
out="$("$PY" - <<'PYEOF'
import json, sys
sys.path.insert(0, "src")
from eoo_engine import DISPATCH_TABLE
pre = json.load(open("protocol/ENGINE_PREREG.json"))["kernel_snapshot"]["kernel_resource_kinds"]
print("OK" if sorted(DISPATCH_TABLE) == sorted(pre) else "BAD", sorted(DISPATCH_TABLE))
PYEOF
)"
case "$out" in OK*) pass dispatch_table_kinds "${out#OK }";; *) fail dispatch_table_kinds "$out";; esac
big="$(wc -l src/eoo_engine/*.py | awk '$2 != "total" && $1 >= 250 {print $2"="$1}')"
[ -z "$big" ] && pass core_module_size "max $(wc -l src/eoo_engine/*.py | awk '$2 != "total"' | sort -n | tail -1 | awk '{print $2"="$1}') lines" \
  || fail core_module_size "$big"
dom="$(grep -n "domains" src/eoo_engine/*.py | head -3)"
[ -z "$dom" ] && pass core_no_domains_reference "grep -n domains src/eoo_engine/*.py: 0 hits" || fail core_no_domains_reference "$dom"

# 4. Dry runs: examples, the OpenPona coverage IR and both Gate-0 domain IRs compile through DISPATCH_TABLE; with
#    no bindings the Engine refuses to load and lists every Unbound item (no defaults).
"$PY" - > "$TMP/dry.txt" 2>&1 <<'PYEOF'
import json, sys
from collections import Counter
from glob import glob
sys.path.insert(0, "src")
from eoo_engine import Engine, LoadError, required_bindings
files = sorted(glob("ontology/examples/*.json")) + ["tests/h15/openpona_coverage_ir.json"] + sorted(glob("domains/*/ir.json"))
for f in files:
    pkg = json.load(open(f))
    need = required_bindings(pkg)
    try:
        Engine(pkg)
        print(f"FAIL dry_run_{f}: Engine loaded with no bindings")
    except LoadError as e:
        same = set(e.problems) == set(need)
        kinds = dict(sorted(Counter(u.kind for u in need).items()))
        print(("PASS" if same and need else "FAIL"), f"dry_run_{f}:", f"{len(need)} unbound refs reported {kinds}")
PYEOF
while IFS= read -r line; do echo "$line"; case "$line" in FAIL*) FAILS=$((FAILS + 1));; esac; done < "$TMP/dry.txt"

# 5. Meta-tests (AGENTS.md section 9): each injected defect must turn its named test red; an unmutated copy is green.
mutate() {  # $1 name, $2 file, $3 old, $4 new, $5 expected failing test
  local d="$TMP/mut_$1"
  mkdir -p "$d" && cp -R src tests ontology protocol domains pyproject.toml "$d"/ 2>/dev/null
  find "$d" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
  if [ "$1" != control ]; then
    "$PY" - "$d/$2" "$3" "$4" <<'PYEOF' || { fail "mutant_$1" "mutation text not found in $2"; return; }
import sys
p, old, new = sys.argv[1:4]
s = open(p).read()
assert s.count(old) == 1, s.count(old)
open(p, "w").write(s.replace(old, new))
PYEOF
  fi
  d="$(cd "$d" && pwd -P)"
  (cd "$d" && HYPOTHESIS_PROFILE=ci "$PY" -m pytest -q -p no:cacheprovider tests/engine -k "not generated_packages" \
     -o addopts="" > "$d/run.log" 2>&1)
  local rc=$? where
  where="$(cd "$d" && "$PY" -c 'import sys; sys.path.insert(0,"src"); import eoo_engine; print(eoo_engine.__file__)')"
  case "$where" in "$d"/*) ;; *) fail "mutant_$1" "harness imported $where, not the copy"; return;; esac
  if [ "$1" = control ]; then
    [ $rc -eq 0 ] && pass mutant_control "unmutated copy green: $(summary "$d/run.log")" \
      || fail mutant_control "unmutated copy rc=$rc $(summary "$d/run.log")"
  elif [ $rc -ne 0 ] && grep -aq "FAILED.*$5" "$d/run.log"; then
    pass "mutant_$1" "killed by $5; $(summary "$d/run.log")"
  else
    fail "mutant_$1" "survived (rc=$rc) $(summary "$d/run.log")"
  fi
}
mutate control "" "" "" ""
mutate deny_override src/eoo_engine/authority.py 'd.allowed = bool(d.allow) and not d.deny and not d.errors' \
  'd.allowed = bool(d.allow)' test_deny_rule_overrides_allow
mutate hard_constraint src/eoo_engine/pipeline.py '    if hard_fail:' '    if False:' \
  test_hard_constraint_blocks_before_commit
mutate idempotency src/eoo_engine/pipeline.py 'if prev["digest"] == intent:' 'if False:' \
  test_idempotent_retry_same_result_no_second_effect
mutate grant_check src/eoo_engine/capabilities.py 'if live.get(getattr(grant, "token", None)) is not grant:' \
  'if False:' test_store_rejects_writes_without_valid_live_grant
mutate default_deny src/eoo_engine/gates.py '    elif allow_declared and ALLOW not in applying:' '    elif False:' \
  test_default_deny_when_no_allow_policy_applies
mutate blind_recall src/eoo_engine/outcome.py \
  'if before == "EXECUTING" and any(i not in rec["responses"] for i in rec["intents"]):' 'if False:' \
  test_crash_between_intent_and_response_is_outcome_unknown

# 6. Repository hygiene: frozen / read-only files untouched; only new paths in the allowed places.
frozen="$("$PY" -c 'import json; d=json.load(open("protocol/FREEZE.json")); fs=d.get("files", d); print("\n".join(sorted(x["path"] if isinstance(x, dict) else x for x in fs)))' 2>/dev/null)"
changed="$(git status --porcelain -- . | awk '{print $2}')"
bad=""
for f in $changed; do
  rel="${f#round2/}"
  case "$rel" in
    src/eoo_engine/*|tests/engine/*|docs/engine_semantics.md|scripts/verify_engine_core.sh) ;;
    *) bad="$bad $rel";;
  esac
  if printf '%s\n' "$frozen" | grep -qxF "$rel"; then bad="$bad FROZEN:$rel"; fi
done
[ -z "$bad" ] && pass repo_scope "changed paths: $(echo $changed | tr '\n' ' ')" || fail repo_scope "unexpected:$bad"
ro="$(git status --porcelain -- protocol hypotheses domains src/eoo_ir src/eoo_dsl src/eoo_openpona experiments/h15)"
[ -z "$ro" ] && pass read_only_paths_untouched "git status on protocol/ hypotheses/ domains/ eoo_ir/dsl/openpona experiments/h15: clean" \
  || fail read_only_paths_untouched "$ro"

# 7. Whole round2 suite and pack check.
"$PY" -m pytest -q -p no:cacheprovider > "$TMP/full.log" 2>&1
rc=$?
s="$(summary "$TMP/full.log")"
if [ $rc -eq 0 ] && ! grep -aqE '[0-9]+ failed' "$TMP/full.log"; then pass full_round2_suite "rc=0; $s"
else fail full_round2_suite "rc=$rc; $s; $(grep -aE '^FAILED' "$TMP/full.log" | head -5 | tr '\n' ' ')"; fi
(PATH="$R2/.venv/bin:$PATH" make check > "$TMP/check.log" 2>&1)
grep -aq "PACK OK" "$TMP/check.log" && pass make_check "$(grep -a 'PACK OK' "$TMP/check.log")" \
  || fail make_check "$(tail -3 "$TMP/check.log" | tr '\n' ' ')"

echo "SUMMARY: $FAILS failing check(s)"
[ "$FAILS" -eq 0 ]
