#!/usr/bin/env bash
# H15 Phase 1 (Gate 0) verification. One line per check: "PASS <name>: <evidence>" or "FAIL <name>: <evidence>".
# Exits non-zero if any check fails. Takes about 5 minutes (the full round2 suite runs once; per-check results
# are then read from its JUnit XML, and every other check re-executes its own probe independently).
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
cd "$ROOT" || exit 2
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAILS=0
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS + 1)); }
ok_or_fail() { if [ "$1" = 0 ]; then pass "$2" "$3"; else fail "$2" "$3"; fi; }
# prints "<n_passed>/<n_total>" for JUnit testcases whose classname contains any of the given module names
junit() { "$PY" - "$TMP/junit.xml" "$@" <<'EOF'
import sys, xml.etree.ElementTree as ET
xml, mods = sys.argv[1], sys.argv[2:]
cases = [c for c in ET.parse(xml).getroot().iter("testcase") if any(m in c.get("classname", "") for m in mods)]
bad = [c for c in cases if c.find("failure") is not None or c.find("error") is not None or c.find("skipped") is not None]
print(f"{len(cases) - len(bad)}/{len(cases)}")
sys.exit(0 if cases and not bad else 1)
EOF
}

# 1. pack check ---------------------------------------------------------------------------------
out=$(PATH="$ROOT/.venv/bin:$PATH" make check 2>&1); rc=$?
if [ $rc = 0 ] && echo "$out" | grep -q '^PACK OK'; then pass pack_check "$(echo "$out" | grep '^PACK OK')"; else fail pack_check "rc=$rc $(echo "$out" | tail -2 | tr '\n' ' ')"; fi

# 2. full round2 suite (also the source of the per-check JUnit results below) ---------------------
export H15_COVERAGE_OUT="$TMP/coverage.txt"
"$PY" -m pytest -q -p no:cacheprovider --junitxml="$TMP/junit.xml" >"$TMP/pytest.log" 2>&1; rc=$?
summary=$("$PY" - "$TMP/junit.xml" <<'EOF'
import sys, xml.etree.ElementTree as ET
r = ET.parse(sys.argv[1]).getroot()
s = r if r.tag == "testsuite" else r.find("testsuite")
t, f, e, k = (int(s.get(x)) for x in ("tests", "failures", "errors", "skipped"))
h15 = sum(1 for c in r.iter("testcase") if "h15" in c.get("classname", ""))
print(f"tests={t} failures={f} errors={e} skipped={k} h15_tests={h15}")
sys.exit(0 if t > 0 and f == 0 and e == 0 and k == 0 and h15 > 0 else 1)
EOF
); src=$?
pytail=$(grep -E '[0-9]+ (passed|failed|error)' "$TMP/pytest.log" | tail -1)
if [ $rc = 0 ] && [ $src = 0 ]; then pass full_pytest "pytest rc=0; $summary; '$pytail'"; else fail full_pytest "pytest rc=$rc; $summary; '$pytail'"; fi

# 3. oracle known-negatives, equivalence, mutation sweep, oracle meta-tests -----------------------
ev=$(junit test_oracle_known_negatives test_oracle_equivalence test_oracle_meta); ok_or_fail $? oracle_known_negatives "oracle self-tests (known negatives, 115 mutation classes, injected oracle defects) passed $ev"
n=$("$PY" -c "
import sys; sys.path.insert(0,'src')
from eoo_ir.mutations import REGISTRY; print(len(REGISTRY))")
[ "${n:-0}" -ge 100 ] && pass mutation_class_count "$n mutation classes registered (each judged non-equivalent with the mutated field named)" || fail mutation_class_count "only ${n:-0} classes"

# 4. no OpenPona in this phase: static test + independent grep with a known-positive control ----------
ev=$(junit test_oracle_static); ok_or_fail $? no_openpona_static_test "static AST+text tests passed $ev"
echo "import OpenPona_control" > "$TMP/control.py"
ctl=$(grep -rli openpona "$TMP/control.py" | wc -l | tr -d ' ')
hits=$(grep -rli openpona src/eoo_ir src/eoo_dsl domains protocol/h15_ambiguity_classes.json ontology/h15_oracle_notes.md tests/h15/dsl_ambiguity_cases.jsonl scripts/domain_build scripts/build_domain_ir.py scripts/build_dsl_ambiguity_cases.py scripts/build_oracle_notes.py 2>/dev/null | wc -l | tr -d ' ')
if [ "$ctl" = 1 ] && [ "$hits" = 0 ]; then pass no_openpona_grep "0 files mention it (control file matched: grep works)"; else fail no_openpona_grep "control=$ctl hits=$hits"; fi

# 5. both real-domain IRs validate (schema + referential), with a known-negative control ------------
ev=$("$PY" - <<'EOF'
import copy, json, sys
sys.path.insert(0, "src")
from eoo_ir import validate
from eoo_ir.conformance import interface_conformance_errors
parts, bad = [], 0
for d in ("manufacturing", "project"):
    ir = json.load(open(f"domains/{d}/ir.json"))
    errs = validate(ir) + interface_conformance_errors(ir)
    bad += len(errs)
    parts.append(f"{d}: " + " ".join(f"{k}={len(ir[k])}" for k in ("object_types", "link_types", "interfaces", "functions", "actions", "policies", "authority_rules", "observation_types", "constraints")) + f" errors={len(errs)}")
ctl = copy.deepcopy(ir); ctl["link_types"][0]["to"] = "NoSuchType"
ce = validate(ctl)
parts.append(f"control(dangling link end)->{len(ce)} error(s) {ce[0].code if ce else '-'}")
print("; ".join(parts))
sys.exit(0 if bad == 0 and ce else 1)
EOF
); ok_or_fail $? domain_irs_validate "$ev"

# 6. DSL round trip, both domains ---------------------------------------------------------------
ev=$("$PY" - <<'EOF'
import json, sys
sys.path.insert(0, "src")
from eoo_dsl import compile, render
from eoo_ir import equivalent
res = []
for d in ("manufacturing", "project"):
    ir = json.load(open(f"domains/{d}/ir.json"))
    text = open(f"domains/{d}/dsl.yaml").read()
    out = compile(text)
    assert text == render(ir), f"{d}: dsl.yaml is not render(ir)"
    assert out == ir, f"{d}: compile(dsl.yaml) != ir.json"
    r = equivalent(ir, out)
    assert r.ok, r.diffs[:3]
    res.append(f"{d}: dsl.yaml == render(ir), compile(dsl.yaml) == ir, equivalent")
print("; ".join(res))
EOF
); ok_or_fail $? dsl_roundtrip_domains "$ev"
ev=$(junit test_dsl_roundtrip); ok_or_fail $? dsl_roundtrip_generated "generated-package round trip + frozen examples + committed dsl.yaml passed $ev"

# 7. DSL ambiguity cases fail closed (re-executed here, plus the suite) ---------------------------
ev=$("$PY" - <<'EOF'
import json, sys
from collections import Counter
sys.path.insert(0, "src")
import eoo_dsl.errors as E
from eoo_dsl import DslError, compile, render
cls = json.load(open("protocol/h15_ambiguity_classes.json"))["classes"]
cases = [json.loads(l) for l in open("tests/h15/dsl_ambiguity_cases.jsonl")]
base = {n: render(json.load(open(f"ontology/examples/{f}.json"))) for n, f in (("M", "manufacturing-minimal"), ("P", "project-domain-minimal"))}
for b in base.values():
    compile(b)  # control: the unmutated bases compile
n = Counter(c["class"] for c in cases)
assert set(n) == {c["id"] for c in cls} and min(n.values()) >= 2, n
for c in cases:
    try:
        compile(c["text"])
    except DslError as e:
        assert isinstance(e, getattr(E, c["dsl_error"])), (c["id"], type(e).__name__)
        continue
    raise SystemExit(f"case {c['id']} was ACCEPTED")
print(f"{len(cases)} cases over {len(n)} classes (min {min(n.values())}/class) all raised the declared typed error; control bases compile")
EOF
); ok_or_fail $? dsl_ambiguity_fail_closed "$ev"
ev=$(junit test_dsl_ambiguity test_dsl_failclosed); ok_or_fail $? dsl_failclosed_suite "ambiguity cases + deletion-mutant property + schema-differential + corruption fuzz + defective-compiler teeth passed $ev"

# 8. generator coverage table complete ------------------------------------------------------------
ev=$(junit test_oracle_coverage); ok_or_fail $? coverage_test "coverage tests passed $ev"
if [ -s "$TMP/coverage.txt" ]; then
  rows=$(wc -l < "$TMP/coverage.txt" | tr -d ' ')
  miss=$(grep -vc "missing=\[\]" "$TMP/coverage.txt")
  full=$(grep -c "missing=\[\]" "$TMP/coverage.txt")
  if [ "$miss" = 0 ] && [ "$rows" -ge 40 ]; then pass coverage_table_complete "$full/$rows coverage items fully reached over 2000 fixed-seed generated packages"; else fail coverage_table_complete "$miss of $rows items have missing members: $(grep -v 'missing=\[\]' "$TMP/coverage.txt" | head -3 | tr '\n' ' ')"; fi
else fail coverage_table_complete "coverage table was not written"; fi

# 9. real-domain provenance, builder reproducibility, notes table ----------------------------------
ev=$(junit test_domains); ok_or_fail $? domain_tests "domain tests (provenance covers every id, source paths exist, source-coverage guard) passed $ev"
out=$("$PY" scripts/build_domain_ir.py --check 2>&1); ok_or_fail $? builders_reproduce_domains "${out:-committed ir.json/dsl.yaml/provenance.md equal builder output}"
out=$("$PY" scripts/build_oracle_notes.py --check 2>&1); ok_or_fail $? oracle_notes_current "$out"

# 10. Gate-0 hash ----------------------------------------------------------------------------------
out=$("$PY" scripts/h15_gate0_hash.py --check 2>&1); ok_or_fail $? gate0_hash_check "$(echo "$out" | head -3 | tr '\n' ' ')"
ev=$(junit test_gate0_hash); ok_or_fail $? gate0_hash_script_detects_change "tamper known-negatives passed $ev"

# 11. protocol freeze untouched ---------------------------------------------------------------------
ev=$("$PY" - <<'EOF'
import hashlib, json, subprocess, sys
fr = json.load(open("protocol/FREEZE.json"))
h = hashlib.sha256()
for f in fr["files"]:
    b = open(f["path"], "rb").read()
    assert hashlib.sha256(b).hexdigest() == f["sha256"], f"FROZEN FILE CHANGED: {f['path']}"
    h.update(f["path"].encode() + b"\0" + b + b"\0")
assert h.hexdigest() == fr["protocol_sha256"], "protocol_sha256 mismatch"
paths = ["protocol/FREEZE.json"] + [f["path"] for f in fr["files"]]
d = subprocess.run(["git", "diff", "--name-only", "HEAD", "--"] + paths, capture_output=True, text=True)
assert d.returncode == 0 and d.stdout.strip() == "", f"git sees changes in frozen files: {d.stdout!r} {d.stderr!r}"
print(f"{len(fr['files'])} frozen files re-hashed == FREEZE.json; protocol_sha256 {fr['protocol_sha256'][:12]} reproduced; git diff vs HEAD clean for FREEZE.json and every frozen file")
EOF
); ok_or_fail $? freeze_unchanged "$ev"

# 12. hygiene -----------------------------------------------------------------------------------------
n=$(grep -rnE "xfail|pytest\.skip|skipif|mark\.skip" tests/h15 2>/dev/null | wc -l | tr -d ' ')
[ "$n" = 0 ] && pass no_skips_or_xfails "0 skip/xfail markers in tests/h15" || fail no_skips_or_xfails "$n markers"
mod=$(git diff --name-only HEAD -- . | tr '\n' ' ')
if [ "$mod" = "round2/pyproject.toml " ]; then pass tracked_changes_limited "only round2/pyproject.toml (new optional extra h15) is modified among tracked files"; else fail tracked_changes_limited "tracked files modified: $mod"; fi

echo "----"
if [ "$FAILS" = 0 ]; then echo "ALL CHECKS PASSED"; exit 0; else echo "$FAILS CHECK(S) FAILED"; exit 1; fi
