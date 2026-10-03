#!/usr/bin/env bash
# P10 acceptance checks for Engine v1.2 (Engine-owned provenance envelope; adapters write it verbatim).
# Prints "PASS <name>: <evidence>" / "FAIL <name>: <evidence>" per check; exits non-zero on any FAIL.
#
# Tests that require "Engine/domain files clean vs HEAD" (H16/H20/H21 evaluator known-positives, the H20
# never-touch-the-repo check) cannot pass on an uncommitted working tree. When round2/src or round2/domains differ
# from HEAD, the FULL round2 suite runs in a scratch clone of this repository with the working changes overlaid and
# committed IN THE CLONE (the real repository is never written). On a clean tree everything runs in place.
#
# Usage: round2/scripts/verify_engine_v1_2.sh        (takes ~20 minutes; the full suite dominates)
#        SKIP_FULL=1 round2/scripts/verify_engine_v1_2.sh   (fast checks only; prints FAIL for the skipped full suite)
set -u
R2="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$R2/.." && pwd)"
PY="$R2/.venv/bin/python"
WORK="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/verify-v12-XXXXXX")" && pwd -P)"  # resolved: /var -> /private/var on macOS
FAILS=0
pass() { echo "PASS $1: $2"; }
fail() { echo "FAIL $1: $2"; FAILS=$((FAILS + 1)); }
# pytest summary line, e.g. "168 passed in 26.19s"; never only the tail, every summary line
summary() { grep -aE "^(=+ )?[0-9]+ (passed|failed|error)|^[0-9]+ (passed|failed)|[0-9]+ failed|[0-9]+ error" "$1" | tail -1; }
run_pytest() {  # name, log, args...
  local name="$1" log="$2"; shift 2
  (cd "$R2" && "$PY" -m pytest -q -p no:cacheprovider "$@" > "$log" 2>&1); local rc=$?
  local s; s="$(summary "$log")"
  if [ $rc -eq 0 ] && echo "$s" | grep -q "passed" && ! echo "$s" | grep -qE "failed|error"; then pass "$name" "$s"
  else fail "$name" "rc=$rc ${s:-no summary} (log $log)"; fi
}

# 1. version constant
v="$(cd "$R2" && PYTHONPATH="$R2/src" "$PY" -c 'from eoo_engine import ENGINE_VERSION; print(ENGINE_VERSION)' 2>&1)"
[ "$v" = "1.2" ] && pass engine-version "ENGINE_VERSION=$v" || fail engine-version "ENGINE_VERSION=$v"

DIRTY="$(cd "$REPO" && git status --porcelain -- round2/src round2/domains round2/tests round2/scripts round2/docs)"
CLEAN_SENSITIVE=(tests/h16/test_evaluate_h16.py tests/h20/test_evaluate_h20.py tests/h21/test_evaluate_h21.py)
NEVER_TOUCH="tests/h20/test_trace_mutants.py::test_mutations_never_touch_the_repository"
DESEL=(); if [ -n "$DIRTY" ]; then for f in "${CLEAN_SENSITIVE[@]}"; do DESEL+=(--ignore="$f"); done; DESEL+=(--deselect="$NEVER_TOUCH"); fi

# 2. targeted suites in place (clean-tree-sensitive evaluator files deferred to the clone when the tree is dirty)
run_pytest tests-engine-domains "$WORK/engine.log" tests/engine tests/domains
run_pytest tests-envelope "$WORK/envelope.log" tests/engine/test_provenance_envelope.py
run_pytest tests-h17 "$WORK/h17.log" tests/h17
run_pytest tests-h18 "$WORK/h18.log" tests/h18
before="$(cd "$REPO" && git status --porcelain -- round2/src/eoo_engine round2/domains | shasum)"
run_pytest tests-h20 "$WORK/h20.log" tests/h20 "${DESEL[@]}"
after="$(cd "$REPO" && git status --porcelain -- round2/src/eoo_engine round2/domains | shasum)"
[ "$before" = "$after" ] && pass h20-mutations-leave-repo-untouched "git status of src/eoo_engine+domains identical before/after the H20 run" \
  || fail h20-mutations-leave-repo-untouched "git status changed during the H20 run"
run_pytest tests-h21 "$WORK/h21.log" tests/h21 "${DESEL[@]}"
run_pytest tests-provenance-rule "$WORK/rule.log" tests/h20/test_provenance_rule.py tests/h20/test_adapters.py

# 3. static checks (python, against the working tree)
pycheck() {  # name, python source on stdin; the snippet prints "OK <evidence>" or anything else = FAIL
  local name="$1" out
  out="$(cd "$R2" && PYTHONPATH="$R2/src:$R2" "$PY" - 2>&1 | tail -1)"
  case "$out" in OK*) pass "$name" "${out#OK }";; *) fail "$name" "$out";; esac
}
pycheck audit-strict-count-zero-no-exceptions <<'PYEOF'
from eoo_h20 import adapter_static as AS
a = AS.audit()
strict = a["violations"] + a["declared_hits"]
ok = AS.DECLARED_EXCEPTIONS == [] and a["declared_exceptions"] == [] and strict == 0 and len(a["files"]) >= 5
print(("OK " if ok else "BAD ") + f"files={len(a['files'])} violations={a['violations']} declared_hits={a['declared_hits']} "
      f"strict={strict} DECLARED_EXCEPTIONS={AS.DECLARED_EXCEPTIONS}")
PYEOF
pycheck audit-known-positive-verbatim-write-clean <<'PYEOF'
from eoo_exp.util import ROOT
from eoo_h20 import adapter_static as AS
a = AS.audit()
hits = [v for r in a["files"] for v in r["violations"] if v["kind"] == "provenance_composition"]
src = (ROOT / "src/eoo_engine_git/adapter.py").read_text()
ok = hits == [] and 'message=effect.get("envelope_text")' in src
print(("OK " if ok else "BAD ") + f"provenance_composition hits on real adapters={len(hits)}; GitAdapter passes envelope_text verbatim={'message=effect.get(\"envelope_text\")' in src}")
PYEOF
pycheck audit-known-negative-old-trailers-flagged <<'PYEOF'
from eoo_exp.util import ROOT
from eoo_h20 import adapter_static as AS
OLD = '''

def _msg(self, subject, trailers):
    if not self.provenance:
        return subject + "\\n"
    return subject + "\\n\\n" + "\\n".join(f"{k}: {v}" for k, v in trailers.items()) + "\\n"


def _trailers(self, meta, writer, rows, base, head, how, files):
    return {"EOO-Execution": meta["execution"], "EOO-Writer": writer, "EOO-Action": meta["action"],
            "EOO-Idempotency-Key": meta.get("idempotency_key") or "-", "EOO-Effects": " ".join(meta["effects"]),
            "EOO-Targets": ",".join(t for t, _ in rows), "EOO-Base": base, "EOO-Head-At-Write": head or "-",
            "EOO-Merge": how, "EOO-Engine-Version": self.engine_version}
'''
f = "src/eoo_engine_git/store.py"
a = AS.audit(overrides={f: (ROOT / f).read_text() + OLD})
vs = [v for r in a["files"] for v in r["violations"]]
comp = [v for v in vs if v["kind"] == "provenance_composition"]
msg = [v for v in vs if v.get("qual") == "_msg"]
ok = len(comp) >= 10 and msg and a["declared_hits"] == 0 and a["violations"] == len(vs) > 0
print(("OK " if ok else "BAD ") + f"planted v1.1 trailer code: violations={a['violations']} (provenance_composition={len(comp)}, "
      f"_msg governance branch={len(msg)}), declared_hits={a['declared_hits']}")
PYEOF
run_pytest tests-provenance-verbatim "$WORK/verbatim.log" tests/h20/test_adapters.py -k "provenance_verbatim or batch_commit_once"
pycheck provenance-verbatim-known-positive-real-adapters <<'PYEOF'
from eoo_h20.provenance_writes import probes
from eoo_h20.trace import Tracer
r = probes(Tracer)
kp = r["known_positive"]
w = {k: v["adapter_provenance_writes"] for k, v in kp.items()}
m = {k: v["adapter_provenance_verbatim_mismatches"] for k, v in kp.items()}
ok = all(x > 0 for x in w.values()) and all(x == 0 for x in m.values()) and r["known_positive_clean"]
print(("OK " if ok else "BAD ") + f"real adapters, text written == effect['envelope_text'] byte for byte: writes={w} mismatches={m}")
PYEOF
pycheck provenance-verbatim-known-negative-appended-line-detected <<'PYEOF'
from eoo_h20 import adapter_static as AS
from eoo_h20.provenance_writes import probes
from eoo_h20.trace import Tracer
r = probes(Tracer)
kn = r["known_negative"]
m = {k: v["adapter_provenance_verbatim_mismatches"] for k, v in kn.items()}
ex = {k: v["first_mismatches"][0]["written"].count("Writer: w1") if v["first_mismatches"] else None for k, v in kn.items()}
static = AS.audit()["violations"]  # the planted line label is not EOO-: the static rule alone cannot see it (behavioural check closes the gap)
ok = r["known_negative_detected"] and all(x == 1 for x in m.values())
print(("OK " if ok else "BAD ") + f"adapter appends 'Writer: w1' (non-EOO label) to the message: mismatches={m} (GitFake, GitAdapter); static audit on real code={static}")
PYEOF
pycheck h16-kernel-kinds-unchanged <<'PYEOF'
import json
from eoo_exp.util import ROOT
from eoo_h16.kernel import dispatch_snapshot, rev_snapshot
live, head = dispatch_snapshot(), rev_snapshot("0a8ce22")["dispatch"]  # last Engine v1.1 commit
pre = sorted(json.loads((ROOT / "protocol/ENGINE_PREREG.json").read_text())["kernel_snapshot"]["kernel_resource_kinds"])
for d in (live, head):
    d.pop("engine_file", None)
ok = live == head and sorted(live["handlers"]) == pre
print(("OK " if ok else "BAD ") + f"dispatch kinds={sorted(live['handlers'])} == v1.1 (0a8ce22): {live == head}; == ENGINE_PREREG kernel kinds: {sorted(live['handlers']) == pre}")
PYEOF
pycheck git-commit-message-is-the-envelope-and-traceable <<'PYEOF'
import subprocess, tempfile
from eoo_engine import ENGINE_VERSION, ProvenanceEnvelope, parse_envelope, render_envelope
from eoo_engine.canon import to_plain
from eoo_h18.rig import EooRig
from domains.project.logic.freeze import git_blob_reader
rig = EooRig(tempfile.mkdtemp(prefix="v12-probe-"), reader=git_blob_reader(), h15_state="RUNNING")
st, ref = rig.store, "refs/heads/main"
st.import_ops(rig.base_ops, source="probe", ref=ref, parent=rig.root)
head0, e = st.head(ref), rig.engine(ref)
rec = e.propose("attach_evidence", {"hypothesis": "H15", "evidence": "exp-h15-002/real-domain-roundtrip.json"}, "researcher-1", idempotency_key="p")
head1 = st.head(ref)
msg = st.repo.read_commit(head1)["message"]
cli = subprocess.run(["git", "-C", str(st.repo.path), "cat-file", "commit", head1], capture_output=True, text=True).stdout.split("\n\n", 1)[1]
first = sorted(rec["envelopes"])[0]
want = render_envelope(ProvenanceEnvelope.from_plain(to_plain(rec["envelopes"][first])))
env = parse_envelope(msg)
prov = [p for p in e.provenance.entries() if p.get("exec") == rec["exec"] and p.get("state") == "RECONCILED_SUCCESS"][-1]
from_exec = {r["commit"] for r in to_plain(prov["responses"]).values()}
bases = {r["base"] for r in to_plain(prov["responses"]).values()}
fsck = subprocess.run(["git", "-C", str(st.repo.path), "fsck", "--strict"], capture_output=True).returncode
checks = {"accepted": rec["state"] == "RECONCILED_SUCCESS", "message==envelope_text (bytes)": msg == want == cli,
          "commit->execution,action": (env.get("execution"), env.get("action")) == (rec["exec"], "attach_evidence"),
          "engine_version": env.get("engine_version") == ENGINE_VERSION == "1.2",
          "execution->commit via ProvenanceLog": from_exec == {head1}, "base in response": bases == {head0},
          "no EOO-Base in message": "EOO-Base" not in msg, "fsck": fsck == 0}
print(("OK " if all(checks.values()) else "BAD ") + "; ".join(f"{k}={v}" for k, v in checks.items()) + f"; commit={head1[:12]} exec={rec['exec']}")
PYEOF

# 4. no provenance composition left in adapter code (plain grep twin of the AST rule)
g="$(cd "$R2" && grep -nE "EOO-|_msg\(|trailers" src/eoo_engine_git/*.py domains/*/adapters/*.py)"
[ -z "$g" ] && pass grep-no-trailer-code-in-adapters "0 matches for EOO-|_msg(|trailers in src/eoo_engine_git and domains/*/adapters" \
  || fail grep-no-trailer-code-in-adapters "$(echo "$g" | head -3 | tr '\n' ' ')"
k="$(cd "$R2" && grep -c "EOO-Execution" src/eoo_engine/provenance.py)"
[ "$k" -ge 1 ] && pass grep-known-positive-label-lives-in-engine "EOO-Execution found $k time(s) in src/eoo_engine/provenance.py (the grep can match)" \
  || fail grep-known-positive-label-lives-in-engine "label not found in the Engine"

# 5. pack check
m="$(cd "$R2" && PATH="$R2/.venv/bin:$PATH" make check 2>&1 | tail -1)"
echo "$m" | grep -q "PACK OK" && pass make-check "$m" || fail make-check "$m"

# 6. full round2 suite: in place on a clean tree; in a scratch clone with the working changes committed there otherwise
full_suite() {  # dir -> runs the suite, sets FULL_LOG
  FULL_LOG="$WORK/full.log"
  (cd "$1" && PYTHONPATH="$1/src:$1" "$PY" -m pytest -q -p no:cacheprovider > "$FULL_LOG" 2>&1); FULL_RC=$?
}
if [ "${SKIP_FULL:-0}" = "1" ]; then
  fail full-round2-suite "skipped (SKIP_FULL=1)"
elif [ -z "$DIRTY" ]; then
  full_suite "$R2"; s="$(summary "$FULL_LOG")"
  [ $FULL_RC -eq 0 ] && ! echo "$s" | grep -qE "failed|error" && pass full-round2-suite "in place, clean tree: $s" \
    || fail full-round2-suite "in place rc=$FULL_RC $s (log $FULL_LOG)"
else
  CL="$WORK/clone"
  git clone -q --no-hardlinks "$REPO" "$CL" >/dev/null 2>&1 && git -C "$CL" checkout -q "$(git -C "$REPO" rev-parse HEAD)" 2>/dev/null
  # overlay: every tracked-modified and untracked (not ignored) file under round2, deletions mirrored
  (cd "$REPO" && git status --porcelain -- round2 | while IFS= read -r line; do
     p="${line:3}"; st="${line:0:2}"
     if [ "$st" = " D" ] || [ "$st" = "D " ]; then rm -f "$CL/$p"; else mkdir -p "$CL/$(dirname "$p")"; cp -R "$REPO/$p" "$CL/$p"; fi
   done)
  find "$CL" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
  git -C "$CL" add -A round2 && git -C "$CL" -c user.name=verify -c user.email=verify@invalid commit -q -m "P10 working tree (verify clone only)"
  want="$(cd "$REPO" && git status --porcelain -- round2 | cut -c4- | sort)"
  got="$(git -C "$CL" diff --name-only HEAD~1 HEAD -- round2 | sort)"
  same_bytes=yes; for p in $want; do [ -e "$REPO/$p" ] && ! cmp -s "$REPO/$p" "$CL/$p" && same_bytes=no; done
  imp="$(cd "$CL/round2" && PYTHONPATH="$CL/round2/src:$CL/round2" "$PY" -c 'import eoo_engine; print(eoo_engine.__file__)')"
  case "$imp" in "$CL"/*) pass clone-imports-clone-code "eoo_engine from $imp";; *) fail clone-imports-clone-code "eoo_engine from $imp";; esac
  if [ "$want" = "$got" ] && [ "$same_bytes" = yes ]; then pass clone-overlay "clone HEAD = real HEAD + exactly the $(echo "$want" | wc -l | tr -d ' ') changed/untracked round2 files, byte-identical"
  else fail clone-overlay "changed-file sets differ or bytes differ (same_bytes=$same_bytes)"; fi
  full_suite "$CL/round2"; s="$(summary "$FULL_LOG")"
  [ $FULL_RC -eq 0 ] && ! echo "$s" | grep -qE "failed|error" && pass full-round2-suite "clone of HEAD $(git -C "$REPO" rev-parse --short HEAD) + working changes: $s" \
    || fail full-round2-suite "clone rc=$FULL_RC $s (log $FULL_LOG)"
  cm="$(grep -cE "^FAILED" "$FULL_LOG")"
  [ "$cm" = "0" ] && pass clean-sensitive-evaluators "h16/h20/h21 evaluator known-positives + never-touch check ran in the clone: 0 FAILED lines" \
    || fail clean-sensitive-evaluators "$cm FAILED lines in the clone run: $(grep -E '^FAILED' "$FULL_LOG" | head -3 | tr '\n' ' ')"
fi

echo "---- $FAILS failing check(s); logs in $WORK"
[ "$FAILS" -eq 0 ]
