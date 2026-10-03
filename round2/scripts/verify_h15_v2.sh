#!/usr/bin/env bash
# H15 v2 (OpenPona v2 surface, no coreference labels) acceptance checks. One line per check:
# "PASS <name>: <evidence>" or "FAIL <name>: <evidence>". Exit 1 if any check FAILs. Run from anywhere.
#   PY=<python with the round2 deps>   (default: the main checkout's round2/.venv; PYTHONPATH is set to this tree)
#   DEV_ROOT=<dir holding exp-h15-v2-dev and its dev pin>   (default: <scratchpad>/h15v2-dev)
#   FULL=1  also run the whole round2 suite
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$R2/.." && pwd)"
PY="${PY:-/Users/d_surchis/work/operational-ontology-poc/round2/.venv/bin/python}"
[ -x "$PY" ] || PY="$R2/.venv/bin/python"
export PYTHONPATH="$R2/src:$R2"
DEV_ROOT="${DEV_ROOT:-$(cd "$R2/../.." && pwd)/h15v2-dev}"
FAILS=0
report() { # name, exit-code, evidence
  if [ "$2" -eq 0 ]; then echo "PASS $1: $3"; else echo "FAIL $1: $3"; FAILS=$((FAILS+1)); fi
}
cd "$R2" || exit 1

# 1. H15 tests, v1 + v2 (every summary line)
out=$("$PY" -m pytest -q -p no:cacheprovider tests/h15 2>&1); rc=$?
report h15_tests_v1_and_v2 $rc "$(echo "$out" | grep -E '^[0-9]+ (passed|failed)|(passed|failed|error).* in [0-9.]+s' | tail -3 | tr '\n' ' ')"

out=$("$PY" -m pytest -q -p no:cacheprovider tests/h15 -k "openpona2 or h15_v2" 2>&1); rc=$?
report h15_v2_tests $rc "$(echo "$out" | grep -E '(passed|failed|error).* in [0-9.]+s' | tail -1)"

# 2. bounded vocabulary: known-positive (v2) and known-negative (v1 must FAIL)
out=$("$PY" - <<'PY' 2>&1
import json
import eoo_openpona, eoo_openpona2
from eoo_h15 import corpus, meaning
pk = []
corpus.generate(200, 21, lambda i, p: pk.append((f"g{i}", p)))
pk += [(d, json.load(open(f"domains/{d}/ir.json"))) for d in ("manufacturing", "project")]
v2 = meaning.bounded_vocabulary(eoo_openpona2.render, pk, meaning.v2_table_size())
v1 = meaning.bounded_vocabulary(eoo_openpona.render, pk, meaning.v1_table_size())
top2 = max(v2["per_size"], key=lambda r: r["size"])
top1 = max(v1["per_size"], key=lambda r: r["size"])
print(f"v2 ok={v2['ok']} distinct={v2['distinct_phrases_total']}/{v2['phrase_table_size']} largest size {top2['size']}: "
      f"{top2['max_distinct_per_package']} phrases | v1 ok={v1['ok']} distinct={v1['distinct_phrases_total']}/"
      f"{v1['phrase_table_size']} sizes over bound={len(v1['sizes_over_bound'])} largest size {top1['size']}: "
      f"{top1['max_distinct_per_package']} phrases")
raise SystemExit(0 if v2["ok"] and not v1["ok"] else 1)
PY
); rc=$?
report bounded_vocabulary_positive_v2_negative_v1 $rc "$out"

# 3. every table line and every committed domain line parses RESOLVED and is a table instance
out=$("$PY" - <<'PY' 2>&1
from openpona.parser import parse
from eoo_openpona2.lines import expected_skeleton, read_line
from eoo_openpona2.table import lines, table_size
bad = [t for t in lines() if parse(t).status != "RESOLVED" or parse(t).skeletons != [expected_skeleton(parse(t).tokens)]]
n = 0
for d in ("manufacturing", "project"):
    for i, ln in enumerate(open(f"domains/{d}/openpona2.op").read().splitlines(), 1):
        read_line(i, ln)
        n += 1
print(f"table lines {table_size()} non-RESOLVED {len(bad)}; domain lines {n} all RESOLVED table instances")
raise SystemExit(1 if bad else 0)
PY
); rc=$?
report all_lines_resolved $rc "$out"

# 4. record-key neutrality + record vocabulary + alpha/shape audit on both domains
out=$("$PY" - <<'PY' 2>&1
import json, re
import eoo_openpona2 as op2
from eoo_h15 import sidecar2
key = re.compile(r"L[1-9][0-9]*\.a[1-9][0-9]*")
msgs, bad = [], 0
for d in ("manufacturing", "project"):
    rec = op2.load_record(open(f"domains/{d}/openpona2.record.json").read())
    text = open(f"domains/{d}/openpona2.op").read()
    ir = json.load(open(f"domains/{d}/ir.json"))
    nonneutral = [k for k in rec if not key.fullmatch(k)]
    a = sidecar2.audit_package(ir, text, rec)
    ok = not nonneutral and a["vocabulary"]["ok"] and a["alpha"]["ok"] and a["shape"]["ok"]
    bad += not ok
    msgs.append(f"{d}: keys={len(rec)} non-neutral={len(nonneutral)} vocab_ok={a['vocabulary']['ok']} "
                f"alpha_ok={a['alpha']['ok']} shape_ok={a['shape']['ok']} classes={a['vocabulary']['slots_by_class']}")
print("; ".join(msgs))
raise SystemExit(1 if bad else 0)
PY
); rc=$?
report record_key_neutrality_and_audit $rc "$out"

# 5. domain round trips (committed v2 renders are fresh and compile to the Gate-0 v1 IRs exactly)
out=$("$PY" scripts/build_openpona2_domains.py --check 2>&1); rc1=$?
out2=$("$PY" - <<'PY' 2>&1
import json
import eoo_openpona2 as op2
from eoo_ir import equivalent
msgs, bad = [], 0
for d in ("manufacturing", "project"):
    ir = json.load(open(f"domains/{d}/ir.json"))
    out = op2.compile(open(f"domains/{d}/openpona2.op").read(), op2.load_record(open(f"domains/{d}/openpona2.record.json").read()))
    exact = json.dumps(out, sort_keys=True) == json.dumps(ir, sort_keys=True)
    bad += not (exact and equivalent(ir, out).ok)
    msgs.append(f"{d}: {sum(len(ir[k]) for k in ir if isinstance(ir[k], list) and k != 'imports')} resources exact={exact}")
print("; ".join(msgs))
raise SystemExit(1 if bad else 0)
PY
); rc=$?
report domain_round_trips $((rc + rc1)) "fresh-render check rc=$rc1 ${out:+($out)}; $out2"

# 6. ambiguity cases fail closed (declared error/code), >= 3 per class, all 12 classes
out=$("$PY" scripts/build_openpona2_ambiguity_cases.py --check 2>&1); rc1=$?
out2=$("$PY" - <<'PY' 2>&1
import json
from collections import Counter
from eoo_h15 import ambiguity, candidate
candidate.use("openpona2")
s = ambiguity.declared_openpona()
n = Counter(c["class"] for c in s["cases"])
print(f"{s['total']} cases: fail_closed={s['fail_closed']} as_declared={s['as_declared']} accepted={s['accepted']} "
      f"crashed={s['crashed']} classes={len(n)}/{len(s['classes_declared'])} min_per_class={min(n.values())}")
ok = (s["fail_closed"] == s["total"] == s["as_declared"] and not s["accepted"] and not s["crashed"]
      and set(n) == set(s["classes_declared"]) and min(n.values()) >= 3)
raise SystemExit(0 if ok else 1)
PY
); rc=$?
report ambiguity_cases_fail_closed $((rc + rc1)) "cases file fresh rc=$rc1; $out2"

# 7. Gate-0 check
out=$("$PY" scripts/h15_gate0_hash.py --check 2>&1); rc=$?
report gate0_check $rc "$(echo "$out" | tail -1)"

# 8. FREEZE unchanged (hashes + git diff on frozen / Gate-0 / prereg / v1 candidate paths)
out=$("$PY" - <<'PY' 2>&1
import hashlib, json, pathlib, subprocess
root = pathlib.Path(".")
fz = json.loads((root / "protocol/FREEZE.json").read_text())
bad = [f["path"] for f in fz["files"] if hashlib.sha256((root / f["path"]).read_bytes()).hexdigest() != f["sha256"]]
cand = json.loads((root / "protocol/H15_CANDIDATE.json").read_text())["files"]
bad += [f["path"] for f in cand if hashlib.sha256((root / f["path"]).read_bytes()).hexdigest() != f["sha256"]]
g0 = [f["path"] for f in json.loads((root / "protocol/H15_GATE0.json").read_text())["files"]]
paths = ["protocol/", "hypotheses/", "experiments/", "src/eoo_ir", "src/eoo_dsl", "src/eoo_openpona/",
         "domains/manufacturing/ir.json", "domains/project/ir.json", "domains/project/ir.v2.json"] + g0
diff = subprocess.run(["git", "status", "--porcelain", "--", *paths], capture_output=True, text=True).stdout.split("\n")
diff = [d for d in diff if d.strip()]
print(f"{len(fz['files'])} frozen + {len(cand)} v1-candidate hashes match={not bad} {bad}; "
      f"git status on read-only paths: {diff or 'clean'}")
raise SystemExit(1 if bad or diff else 0)
PY
); rc=$?
report freeze_and_readonly_unchanged $rc "$out"

# 9. no new tokens; parser pinned
out=$("$PY" - <<'PY' 2>&1
import json, hashlib, pathlib
from importlib.metadata import distribution
import openpona
from eoo_openpona2.table import lines
pin = json.loads(pathlib.Path("hypotheses/h15/contract.json").read_text())["experiment"]["openpona_pin"]
du = json.loads(distribution("openpona-language-corpus").read_text("direct_url.json"))
pkg = pathlib.Path(openpona.__file__).parent
toks = {t for x in lines() for t in x.split()}
outside = sorted(toks - set(openpona.TOKENS))
ok = (not outside and du["vcs_info"]["commit_id"].startswith(pin["commit"])
      and hashlib.sha256((pkg / "tokens.csv").read_bytes()).hexdigest() == pin["tokens_csv_sha256"]
      and hashlib.sha256((pkg / "grammar.lark").read_bytes()).hexdigest() == pin["grammar_lark_sha256"])
print(f"table uses {len(toks)} of {len(openpona.TOKENS)} pinned tokens, outside={outside}; parser commit {du['vcs_info']['commit_id'][:9]}")
raise SystemExit(0 if ok else 1)
PY
); rc=$?
report no_new_tokens_parser_pinned $rc "$out"

# 10. the v1 harness path reproduces the committed exp-h15-002 evidence
out=$("$PY" - <<'PY' 2>&1
import json
from eoo_h15 import ambiguity, domains, run
from eoo_h15.util import canon
P = lambda f: json.load(open(f"experiments/h15/exp-h15-002/{f}"))["payload"]
a = canon(ambiguity.declared_openpona()) == canon(P("ambiguity-corpus.json")["declared"]["openpona"])
r = canon(domains.run()) == canon(P("real-domain-roundtrip.json"))
dom = {d: json.load(open(f"domains/{d}/ir.json")) for d in ("manufacturing", "project")}
s = canon(run._sidecar(dom, [])["domains"]) == canon(P("sidecar-audit.json")["domains"])
print(f"declared cases identical={a}; real-domain round trip identical={r}; sidecar domain audit identical={s}")
raise SystemExit(0 if a and r and s else 1)
PY
); rc=$?
report v1_path_identical $rc "$out"

# 11. generated documents are fresh
out=$("$PY" scripts/build_openpona2_encoding.py --check 2>&1); rc=$?
report encoding_doc_fresh $rc "${out:-ontology/openpona2_encoding.md matches the phrase table}"

# 12. pack check
out=$(cd "$R2" && "$PY" scripts/check_pack.py 2>&1); rc=$?
report make_check $rc "$(echo "$out" | head -1)"

# 13. development run exp-h15-v2-dev (outside experiments/): evidence evaluates under the v2 evaluator
DEV="$DEV_ROOT/exp-h15-v2-dev"; DEVPIN="$DEV_ROOT/H15_V2_CANDIDATE.dev.json"
if [ -d "$DEV" ] && [ -f "$DEVPIN" ]; then
  out=$("$PY" - "$DEV" "$DEVPIN" <<'PY' 2>&1
import sys
from eoo_h15 import evaluate_v2
d, pin = sys.argv[1], sys.argv[2]
v = evaluate_v2.evaluate(d, candidate_pin=pin)
p = {r["id"]: r["value"] for k in v["predicates"] for r in v["predicates"][k]}
n = v["numbers"]
print(f"verdict={v['verdict']} protocol_valid={v['common']['protocol_valid']} complete={v['common']['required_evidence_complete']} "
      f"S={[p[k] for k in ('S1','S2','S3','S4','S5','S6')]} R={[p[k] for k in ('R1','R2','R3','R4')]} "
      f"V={[p[k] for k in ('V1','V2','V3')]} valid_cases={n.get('generated_valid_cases')} op_failed={n.get('openpona_failed')} "
      f"meaning={n.get('meaning_rule', {}) and n['meaning_rule'].get('ok')} sidecar={n.get('indispensable_sidecar_count')} "
      f"(V1 here is the dev pin vs the files now on disk)")
raise SystemExit(0 if v["verdict"] != "INVALID" and v["common"]["required_evidence_complete"] else 1)
PY
); rc=$?
  report dev_run_evaluates $rc "$out"
  out=$("$PY" scripts/h15_v2_candidate.py --check "$DEVPIN" 2>&1); rc=$?
  report dev_pin_matches_candidate_files $rc "$out"
else
  report dev_run_evaluates 1 "missing $DEV or $DEVPIN"
fi

# 14. optional: the whole round2 suite
if [ "${FULL:-0}" = "1" ]; then
  out=$("$PY" -m pytest -q -p no:cacheprovider 2>&1); rc=$?
  report full_round2_suite $rc "$(echo "$out" | grep -E '(passed|failed|error).* in [0-9.]+s' | tail -1)"
fi

echo "verify_h15_v2: $FAILS FAIL(s)"
[ "$FAILS" -eq 0 ]
