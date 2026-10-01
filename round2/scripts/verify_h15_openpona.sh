#!/usr/bin/env bash
# H15 Phase 2 (OpenPona surface) acceptance checks. One line per check: "PASS <name>: <evidence>" or
# "FAIL <name>: <evidence>". Exit status = number of FAILs (capped at 1). Run from anywhere.
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$R2/.." && pwd)"
PY="$R2/.venv/bin/python"
FAILS=0
report() { # name, exit-code, evidence
  if [ "$2" -eq 0 ]; then echo "PASS $1: $3"; else echo "FAIL $1: $3"; FAILS=$((FAILS+1)); fi
}
cd "$R2" || exit 1

out=$("$PY" scripts/h15_gate0_hash.py --check 2>&1); rc=$?
report gate0_check $rc "$(echo "$out" | tail -1)"

out=$("$PY" - <<'PY' 2>&1
import hashlib, json, pathlib, subprocess
root = pathlib.Path(".")
fz = json.loads((root / "protocol/FREEZE.json").read_text())
bad = [f["path"] for f in fz["files"] if hashlib.sha256((root / f["path"]).read_bytes()).hexdigest() != f["sha256"]]
g0 = [f["path"] for f in json.loads((root / "protocol/H15_GATE0.json").read_text())["files"]]
paths = ["protocol/FREEZE.json", "protocol/H15_GATE0.json"] + [f["path"] for f in fz["files"]] + g0
diff = subprocess.run(["git", "diff", "--name-only", "HEAD", "--", *paths], capture_output=True, text=True).stdout.split()
print(f"{len(fz['files'])} frozen hashes match={not bad} {bad}; git diff vs HEAD on {len(paths)} frozen/gate0 paths: {diff or 'none'}")
raise SystemExit(1 if bad or diff else 0)
PY
); rc=$?
report freeze_unchanged $rc "$out"

out=$("$PY" - <<'PY' 2>&1
import hashlib, json, pathlib
from importlib.metadata import distribution
import openpona
pin = json.loads(pathlib.Path("hypotheses/h15/contract.json").read_text())["experiment"]["openpona_pin"]
du = json.loads(distribution("openpona-language-corpus").read_text("direct_url.json"))
pkg = pathlib.Path(openpona.__file__).parent
tok = hashlib.sha256((pkg / "tokens.csv").read_bytes()).hexdigest()
gr = hashlib.sha256((pkg / "grammar.lark").read_bytes()).hexdigest()
pyproject = pathlib.Path("pyproject.toml").read_text()
ok = (du["url"] == pin["repository"] and du["vcs_info"]["commit_id"] == "97a9b9e8ca8800fda0a22f51ea59fccb6f60f35b"
      and tok == pin["tokens_csv_sha256"] and gr == pin["grammar_lark_sha256"]
      and "openpona-language-corpus @ git+https://github.com/demithras/openpona-language-corpus@97a9b9e8ca8800fda0a22f51ea59fccb6f60f35b" in pyproject)
print(f"direct_url commit={du['vcs_info']['commit_id']} url={du['url']} tokens.csv={tok[:12]}.. grammar.lark={gr[:12]}.. (contract pin {pin['commit']}) pyproject_pin={'yes' if 'openpona-language-corpus @ git+' in pyproject else 'no'}")
raise SystemExit(0 if ok else 1)
PY
); rc=$?
report openpona_pinned $rc "$out"

out=$("$PY" - <<'PY' 2>&1
import ast, pathlib
bad = []
for p in sorted(pathlib.Path("src/eoo_openpona").glob("*.py")):
    t = p.read_text()
    if "setattr" in t or "monkeypatch" in t:
        bad.append(f"{p.name}: setattr/monkeypatch")
    for n in ast.walk(ast.parse(t)):
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("openpona"):
            if (n.module, [a.name for a in n.names]) not in (("openpona.parser", ["parse"]), ("openpona", ["SEMANTIC"])):
                bad.append(f"{p.name}: from {n.module} import {[a.name for a in n.names]}")
print(f"imports of the pinned package limited to openpona.parser.parse and openpona.SEMANTIC; no patching: {bad or 'ok'}")
raise SystemExit(1 if bad else 0)
PY
); rc=$?
report parser_unmodified $rc "$out"

out=$("$PY" - <<'PY' 2>&1
import json, pathlib, re, sys
sys.path.insert(0, "src")
from openpona.parser import parse
key = re.compile(r"L[1-9][0-9]*\.a[1-9][0-9]*")
msgs, bad = [], 0
for d in ("manufacturing", "project"):
    lines = pathlib.Path(f"domains/{d}/openpona.op").read_text().splitlines()
    st = {}
    for ln in lines:
        r = parse(ln)
        s = "META" if any(re.search(r"D\d+\(", sk) for sk in r.skeletons) else r.status
        st[s] = st.get(s, 0) + 1
    rec = json.loads(pathlib.Path(f"domains/{d}/openpona.record.json").read_text())
    nonneutral = [k for k in rec if not key.fullmatch(k)] + [k for k, v in rec.items() if not isinstance(v, str)]
    beyond = [k for k in rec if key.fullmatch(k) and int(k[1:].split(".")[0]) > len(lines)]
    bad += sum(v for k, v in st.items() if k != "RESOLVED") + len(nonneutral) + len(beyond)
    msgs.append(f"{d}: {len(lines)} lines {st}; record {len(rec)} keys, non-neutral/non-string={len(nonneutral)}, beyond-text={len(beyond)}")
print("; ".join(msgs))
raise SystemExit(1 if bad else 0)
PY
); rc=$?
report rendered_lines_resolved_and_record_keys_neutral $rc "$out"

out=$("$PY" scripts/build_openpona_domains.py --check 2>&1 && "$PY" scripts/build_openpona_encoding.py --check 2>&1 \
      && "$PY" scripts/build_openpona_ambiguity_cases.py --check 2>&1); rc=$?
report committed_artifacts_fresh $rc "${out:-openpona.op/record.json (both domains), openpona_encoding.md, openpona_ambiguity_cases.jsonl equal a fresh build}"

out=$("$PY" - <<'PY' 2>&1
import json, pathlib, sys
sys.path.insert(0, "src")
from eoo_ir import equivalent, validate
from eoo_openpona import compile, load_record
msgs, bad = [], 0
for d in ("manufacturing", "project"):
    ir = json.loads(pathlib.Path(f"domains/{d}/ir.json").read_text())
    try:
        out = compile(pathlib.Path(f"domains/{d}/openpona.op").read_text(),
                      load_record(pathlib.Path(f"domains/{d}/openpona.record.json").read_text()))
    except Exception as e:  # noqa: BLE001 - reported as a FAIL with its message
        bad += 1
        msgs.append(f"{d}: compile raised {type(e).__name__}: {str(e)[:160]}")
        continue
    eq = equivalent(ir, out)
    exact = out == ir
    bad += (not exact) + (not eq.ok) + bool(validate(out))
    n = sum(len(ir[k]) for k in ("object_types", "link_types", "interfaces", "functions", "actions", "policies",
                                 "authority_rules", "observation_types", "constraints"))
    msgs.append(f"{d}: {n} resources, exact={exact}, equivalent={eq.ok} {eq.diffs[:2]}")
print("; ".join(msgs))
raise SystemExit(1 if bad else 0)
PY
); rc=$?
report domain_roundtrip $rc "$out"

out=$("$PY" - <<'PY' 2>&1
import json, pathlib, sys
from collections import Counter
sys.path.insert(0, "src")
from eoo_openpona import OpenPonaError, compile, load_record
classes = [c["id"] for c in json.loads(pathlib.Path("protocol/h15_ambiguity_classes.json").read_text())["classes"]]
cases = [json.loads(x) for x in pathlib.Path("tests/h15/openpona_ambiguity_cases.jsonl").read_text().splitlines()]
ok, wrong = Counter(), []
for c in cases:
    try:
        compile(c["text"], load_record(c["record_json"]) if "record_json" in c else c["record"])
        wrong.append(f"{c['id']}: ACCEPTED")
    except OpenPonaError as e:
        if type(e).__name__ == c["error"] and e.code == c["code"]:
            ok[c["class"]] += 1
        else:
            wrong.append(f"{c['id']}: {type(e).__name__}/{e.code} != {c['error']}/{c['code']}")
thin = [k for k in classes if ok[k] < 3]
print(f"{sum(ok.values())}/{len(cases)} cases fail closed as declared; per class min={min(ok[k] for k in classes)} "
      f"over {len(classes)} classes; under 3: {thin or 'none'}; wrong: {wrong or 'none'}")
raise SystemExit(1 if wrong or thin else 0)
PY
); rc=$?
report ambiguity_cases_fail_closed $rc "$out"

out=$("$PY" - <<'PY' 2>&1
import json, pathlib, sys
sys.path.insert(0, "src")
import eoo_openpona.gaps as g
data = json.loads(pathlib.Path("ontology/openpona_gaps.json").read_text())
ok = isinstance(data, list) and len(g.gaps()) == len(data)
print(f"openpona_gaps.json is a list of {len(data)} entries, all wired to render(): {ok}")
raise SystemExit(0 if ok else 1)
PY
); rc=$?
report gaps_file_wired $rc "$out"

out=$(PATH="$R2/.venv/bin:$PATH" make -s check 2>&1); rc=$?
echo "$out" | grep -q "PACK OK" || rc=1
report make_check $rc "$(echo "$out" | tail -1)"

if [ "${VERIFY_SKIP_PYTEST:-0}" = "1" ]; then  # for quick known-negative runs only: a skip is never a PASS
  report pytest_full_round2 1 "skipped (VERIFY_SKIP_PYTEST=1)"
else
  LOG="${TMPDIR:-/tmp}/verify_h15_openpona_pytest.$$.log"
  "$PY" -m pytest -q -p no:cacheprovider > "$LOG" 2>&1; rc=$?
  summary=$(grep -E "[0-9]+ (passed|failed).* in [0-9.]+s" "$LOG" | tail -1)
  failed=$(grep -E "^(FAILED|ERROR) " "$LOG" | head -5 | tr '\n' ';')
  report pytest_full_round2 $rc "${summary:-no summary line} ${failed}"
  rm -f "$LOG"
fi

echo "verify_h15_openpona: $FAILS FAIL(s)"
[ "$FAILS" -eq 0 ]
