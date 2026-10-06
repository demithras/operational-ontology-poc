#!/usr/bin/env bash
# P5c verify: Engine v1.1 closes the exp-h17-001 returned-record gate bypass without other behaviour change.
# One line per check: "PASS <name>: <evidence>" / "FAIL <name>: <evidence>". Exit 1 on any FAIL.
# FULL=0 skips the ~10 min whole-suite run (default FULL=1).
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$R2/.." && pwd)"
PY="$R2/.venv/bin/python"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP:?}"' EXIT
FAILS=0
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS + 1)); }

# summary "<pytest log>" -> "N passed[, M failed...]" ; never trust exit code alone
summary() { grep -aE "^[0-9]+ (passed|failed)|^=+ .*(passed|failed|error).* =+$|^[0-9]+ passed" "$1" | tail -1 | sed 's/=//g;s/^ *//'; }

run_pytest() {  # name, log, args...
  local name="$1" log="$2"; shift 2
  (cd "$R2" && "$PY" -m pytest -q -p no:cacheprovider "$@" > "$log" 2>&1); local rc=$?
  local s; s="$(summary "$log")"
  if [ $rc -eq 0 ] && echo "$s" | grep -qE "[1-9][0-9]* passed" && ! echo "$s" | grep -qE "failed|error"; then
    pass "$name" "rc=$rc; $s"
  else
    fail "$name" "rc=$rc; $s; failures: $(grep -aE '^(FAILED|ERROR) ' "$log" | head -5 | tr '\n' ' ')"
  fi
}

# 1. tamper regressions (synthetic + both domain packs), engine, domain, h17-agent tests
run_pytest tamper_regressions "$TMP/tamper.log" tests/engine/test_v1_1_tamper.py -rA
N_TAMPER=$(grep -acE "^PASSED tests/engine/test_v1_1_tamper.py" "$TMP/tamper.log")
if [ "$N_TAMPER" -ge 21 ]; then pass tamper_regressions_count "$N_TAMPER tests PASSED (expected >= 21)"
else fail tamper_regressions_count "$N_TAMPER tests PASSED (expected >= 21)"; fi
run_pytest engine_tests "$TMP/engine.log" tests/engine
run_pytest domain_tests "$TMP/domains.log" tests/domains
run_pytest h17_agent_tests "$TMP/h17a.log" tests/h17/test_h17_agents.py

# 2. the exp-h17-001 harness rows, run directly through both domain packs
(cd "$R2" && "$PY" - > "$TMP/rows.txt" 2>&1 <<'EOF'
from eoo_h17 import tamper
from eoo_h17.agents import run_attack
from eoo_h17.drivers import new_driver
for d in ("manufacturing", "project"):
    for n, f in tamper.TAMPER_BOTH + (tamper.TAMPER_MFG if d == "manufacturing" else []):
        drv = new_driver(d, "std")
        r = run_attack(drv, n, "tamper", f)
        print("ROW", d, n, r["violation"], r["world_changed"], r["exception"], r["unexpected_exception"],
              len(drv.engine.effect_log), drv.external_count())
EOF
)
ATT=$(grep -a "^ROW" "$TMP/rows.txt" | grep -v " control_" )
CTL=$(grep -a "^ROW" "$TMP/rows.txt" | grep " control_" )
N_ATT=$(echo "$ATT" | grep -c "ROW")
N_ATT_OK=$(echo "$ATT" | grep -cE " False False CapabilityError False 0 0$")
if [ "$N_ATT" -eq 4 ] && [ "$N_ATT_OK" -eq 4 ]; then
  pass h17_tamper_attacks_zero_effects "4/4 attack rows: violation=False world_changed=False exception=CapabilityError effects=0 external=0"
else fail h17_tamper_attacks_zero_effects "$N_ATT rows, $N_ATT_OK ok: $(echo "$ATT" | tr '\n' ';')"; fi
N_CTL=$(echo "$CTL" | grep -c "ROW")
C_OK=$(echo "$CTL" | grep -cE "control_state_no_tamper_then_recover False False None False 0 0$|control_inputs_no_tamper False True None False 1 1$")
if [ "$N_CTL" -eq 3 ] && [ "$C_OK" -eq 3 ]; then
  pass h17_controls_unchanged "3/3 controls as exp-h17-001 (state controls 0 effects, inputs control 1 effect)"
else fail h17_controls_unchanged "$N_CTL rows, $C_OK ok: $(echo "$CTL" | tr '\n' ';')"; fi

# 3. known-negatives: each defence layer is removed in a COPY of src/eoo_engine (PYTHONPATH first, pytest's
#    pythonpath=src disabled) and the regression file must fail exactly the expected set.
"$PY" - "$R2/src/eoo_engine" "$TMP" <<'EOF2'
import shutil, sys
src, tmp = sys.argv[1], sys.argv[2]
SNAP = [("snapshot.py", "    return _seal(to_plain(v))\n", "    return v  # MUTANT: v1 aliasing\n"),
        ("snapshot.py", "        return snapshot(self._get(xid))\n", "        return self._get(xid)  # MUTANT\n")]
GP = [("gatepass.py", '    xid = rec["exec"]\n    journal = list(eng.journal)\n',
       '    return None  # MUTANT: no gate-pass check\n    xid = rec["exec"]\n    journal = list(eng.journal)\n')]
for name, muts in (("A", SNAP), ("B", GP), ("C", SNAP + GP)):
    dst = f"{tmp}/{name}/eoo_engine"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    for f, old, new in muts:
        s = open(f"{dst}/{f}").read()
        assert s.count(old) == 1, (name, f, old)
        open(f"{dst}/{f}", "w").write(s.replace(old, new))
EOF2
T=tests/engine/test_v1_1_tamper.py
EXP_A="$T::test_domain_exp_h17_001_tamper_attacks_end_with_zero_effects[manufacturing]
$T::test_domain_exp_h17_001_tamper_attacks_end_with_zero_effects[project]
$T::test_every_returned_record_refuses_mutation_and_shares_no_container_with_internal_state
$T::test_synth_inputs_tamper_then_approve
$T::test_synth_state_flip_denied_to_approved_then_recover[fill_box-inputs0]
$T::test_synth_state_flip_denied_to_approved_then_recover[ship_box-inputs1]
$T::test_synth_state_flip_denied_to_pending_then_approve"
EXP_B="$T::test_domain_internal_inputs_tamper_then_approve_is_denied
$T::test_domain_internal_state_flip_to_approved_then_recover_is_denied[manufacturing]
$T::test_domain_internal_state_flip_to_approved_then_recover_is_denied[project]
$T::test_domain_internal_state_flip_to_pending_then_approve_is_denied
$T::test_synth_crash_after_approved_then_tampered_inputs_on_recover
$T::test_synth_inputs_tamper_then_approve
$T::test_synth_state_flip_denied_to_approved_then_recover[fill_box-inputs0]
$T::test_synth_state_flip_denied_to_approved_then_recover[ship_box-inputs1]
$T::test_synth_state_flip_denied_to_pending_then_approve"
for M in A B; do
  ENGFILE=$(cd "$R2" && PYTHONPATH="$TMP/$M" "$PY" -c "import eoo_engine; print(eoo_engine.__file__)")
  (cd "$R2" && PYTHONPATH="$TMP/$M" "$PY" -m pytest -q -p no:cacheprovider -o pythonpath= "$T" > "$TMP/mut$M.log" 2>&1)
  GOT=$(grep -aE "^FAILED " "$TMP/mut$M.log" | sed 's/^FAILED //;s/ - .*//' | sort)
  if [ "$M" = A ]; then WANT=$(echo "$EXP_A" | sort); LAYER="snapshot returns removed (v1 aliasing)"; else WANT=$(echo "$EXP_B" | sort); LAYER="gate-pass check removed"; fi
  case "$ENGFILE" in "$TMP/$M/"*) ;; *) fail "known_negative_$M" "imported the real Engine ($ENGFILE)"; continue;; esac
  if [ "$GOT" = "$WANT" ]; then pass "known_negative_$M" "$LAYER -> exactly the expected $(echo "$WANT" | wc -l | tr -d ' ') tests fail; $(summary "$TMP/mut$M.log")"
  else fail "known_negative_$M" "$LAYER: failing set differs. got=[$(echo "$GOT" | tr '\n' ' ')] want=[$(echo "$WANT" | tr '\n' ' ')]"; fi
done

# 4. exp-h17-001 harness rows per layer: each layer alone closes the 4 attacks; both removed (= v1) reopens all 4
for M in A B C; do
  (cd "$R2" && PYTHONPATH="$TMP/$M" "$PY" - > "$TMP/rows$M.txt" 2>&1 <<'EOF2'
import eoo_engine
from eoo_h17 import tamper
from eoo_h17.agents import run_attack
from eoo_h17.drivers import new_driver
print("ENGINE", eoo_engine.__file__)
for d in ("manufacturing", "project"):
    for n, f in tamper.TAMPER_BOTH + (tamper.TAMPER_MFG if d == "manufacturing" else []):
        if not n.startswith("control"):
            r = run_attack(new_driver(d, "std"), n, "tamper", f)
            print("ROW", d, n, r["violation"], r["world_changed"], r["exception"])
EOF2
  )
  OKIMP=$(grep -ac "^ENGINE $TMP/$M/" "$TMP/rows$M.txt")
  NV=$(grep -a "^ROW" "$TMP/rows$M.txt" | awk '$4=="True"' | wc -l | tr -d ' ')
  NR=$(grep -ac "^ROW" "$TMP/rows$M.txt")
  if [ "$M" = C ]; then WANTV=4; DESC="both layers removed (= Engine v1)"; else WANTV=0; DESC="only $( [ $M = A ] && echo 'gate-pass check' || echo 'snapshot returns') active"; fi
  if [ "$OKIMP" -eq 1 ] && [ "$NR" -eq 4 ] && [ "$NV" -eq "$WANTV" ]; then pass "harness_rows_$M" "$DESC: $NV/4 violations (expected $WANTV)"
  else fail "harness_rows_$M" "$DESC: imported_mutant=$OKIMP rows=$NR violations=$NV (expected $WANTV)"; fi
done

# 5. H16 domain-identity audit + kernel diff (r2-engine-core -> live v1.1)
(cd "$R2" && "$PY" - > "$TMP/h16.txt" 2>&1 <<'EOF2'
from eoo_h16.detectors import audit_sources, changed_is_clean, kernel_diff
from eoo_h16.kernel import live_snapshot, rev_snapshot
a = audit_sources()
e = a["scopes"]["engine_core"]
print("AUDIT", a["domain_identity_branches"], a["domain_identity_literals"], e["files_scanned"], a["token_count"])
d = kernel_diff(rev_snapshot("r2-engine-core"), live_snapshot())
print("KERNEL", d["new_kernel_primitive_kind_count"], len(d["removed_kinds"]), len(d["dispatch_handlers_changed"]),
      d["dispatch_order_changed"], d["schema_unchanged"], changed_is_clean(d))
EOF2
)
read -r _ BR LIT NF NT <<< "$(grep -a '^AUDIT' "$TMP/h16.txt")"
if [ "${BR:-x}" = 0 ] && [ "${LIT:-x}" = 0 ] && [ "${NF:-0}" -ge 21 ]; then
  pass h16_domain_identity_audit "branches=$BR literals=$LIT (engine_core files scanned=$NF incl. snapshot.py+gatepass.py, tokens=$NT)"
else fail h16_domain_identity_audit "$(cat "$TMP/h16.txt" | tail -3 | tr '\n' ' ')"; fi
read -r _ NK RK HC OC SU CL <<< "$(grep -a '^KERNEL' "$TMP/h16.txt")"
if [ "${NK:-x}" = 0 ] && [ "${RK:-x}" = 0 ] && [ "${HC:-x}" = 0 ] && [ "${OC:-x}" = False ] && [ "${SU:-x}" = True ] && [ "${CL:-x}" = True ]; then
  pass h16_kernel_diff "vs r2-engine-core: new kinds=$NK removed=$RK handlers changed=$HC order changed=$OC schema unchanged=$SU clean=$CL"
else fail h16_kernel_diff "$(grep -a '^KERNEL' "$TMP/h16.txt" || tail -3 "$TMP/h16.txt")"; fi

# 6. version constant, provenance, docs
V=$(cd "$R2" && "$PY" -c "import eoo_engine; print(eoo_engine.ENGINE_VERSION)")
[ "$V" = "1.1" ] && pass engine_version "eoo_engine.ENGINE_VERSION=$V" || fail engine_version "got '$V'"
if grep -q '^## 8. Returned values and the gate-pass record' "$R2/docs/engine_semantics.md" && grep -q 'APPROVED | DENIED' "$R2/docs/engine_semantics.md"; then
  pass docs_engine_semantics "section 8 + APPROVED->DENIED (gate_pass) row present"
else fail docs_engine_semantics "section 8 or transition row missing"; fi

# 7. read-only paths untouched (working tree vs HEAD), FREEZE intact
RO=$(cd "$REPO" && git status --porcelain -- round2/src/eoo_h17 round2/oracles round2/experiments round2/protocol \
     round2/hypotheses round2/src/eoo_ir round2/src/eoo_dsl round2/src/eoo_openpona round2/src/eoo_h16 \
     round2/src/eoo_engine/registry.py 'round2/domains/*/ir*.json' 'domains/*/ir*.json')
[ -z "$RO" ] && pass readonly_paths_untouched "git status clean for h17/h16/ir/dsl/openpona/oracles/experiments/protocol/hypotheses/registry.py/domain IR" \
  || fail readonly_paths_untouched "$(echo "$RO" | tr '\n' ' ')"
MC=$(cd "$R2" && PATH="$R2/.venv/bin:$PATH" make check 2>&1 | tail -3)
echo "$MC" | grep -q "PACK OK" && pass make_check "PACK OK" || fail make_check "$(echo "$MC" | tr '\n' ' ')"

# 8. full round2 suite (~10 min). tests/h16/test_evaluate_h16.py runs a real H16 run whose evidence records
#    "engine_core_working_tree_equals_head"; with UNCOMMITTED engine edits that is False -> verdict INVALID (V3) and
#    11 of its tests fail BY DESIGN. So: if src/eoo_engine is dirty, the full-suite failures must be exactly those 11,
#    and the same file must pass in a scratch clone where the working changes are committed.
H16_DIRTY="test_dirty_mutation_control_is_invalid test_domain_branch_hit_is_rejected test_known_positive_is_supported
test_literal_only_hit_is_not_support_but_not_reject test_load_failure_in_generated_is_inconclusive
test_missing_requirement_is_inconclusive test_new_kernel_kind_is_rejected test_rename_invariance_broken_is_rejected
test_surviving_mutant_blocks_support test_too_few_cases_is_inconclusive test_working_tree_differs_from_head_is_invalid"
DIRTY=$(cd "$REPO" && git status --porcelain -- round2/src/eoo_engine)
if [ "${FULL:-1}" = 1 ]; then
  if [ -z "$DIRTY" ]; then
    run_pytest full_round2_suite "$TMP/full.log"
  else
    (cd "$R2" && "$PY" -m pytest -q -p no:cacheprovider > "$TMP/full.log" 2>&1)
    GOT=$(grep -aE "^(FAILED|ERROR) " "$TMP/full.log" | sed -E 's/^(FAILED|ERROR) //;s/ - .*//' | sort)
    WANT=$(for t in $H16_DIRTY; do echo "tests/h16/test_evaluate_h16.py::$t"; done | sort)
    if [ "$GOT" = "$WANT" ]; then
      pass full_round2_suite "$(summary "$TMP/full.log"); engine uncommitted -> the only failures are the 11 H16-evaluator V3 dirty-tree tests (by design)"
    else fail full_round2_suite "$(summary "$TMP/full.log"); unexpected failing set: $(comm -3 <(echo "$GOT") <(echo "$WANT") | tr '\n' ' ')"; fi
    git clone -q --no-hardlinks "$REPO" "$TMP/clone" && git -C "$TMP/clone" checkout -q "$(git -C "$REPO" rev-parse HEAD)"
    (cd "$REPO" && git status --porcelain --untracked-files=all -- round2 | sed 's/^...//') | while read -r f; do
      mkdir -p "$(dirname "$TMP/clone/$f")"; cp "$REPO/$f" "$TMP/clone/$f"; done
    git -C "$TMP/clone" add -A && git -C "$TMP/clone" -c user.name=verify -c user.email=verify@invalid commit -q -m "scratch: working changes"
    (cd "$TMP/clone/round2" && "$PY" -m pytest -q -p no:cacheprovider tests/h16/test_evaluate_h16.py > "$TMP/h16clone.log" 2>&1); rc=$?
    S2=$(summary "$TMP/h16clone.log")
    if [ $rc -eq 0 ] && ! echo "$S2" | grep -q failed; then pass h16_evaluator_on_committed_clone "rc=0; $S2 (scratch clone at HEAD + working changes committed)"
    else fail h16_evaluator_on_committed_clone "rc=$rc; $S2"; fi
  fi
  grep -aE "^FAILED |^ERROR " "$TMP/full.log" | head -20
else echo "SKIP full_round2_suite: FULL=0"; fi

echo "SUMMARY: $FAILS failing check(s)"
[ "$FAILS" -eq 0 ]
