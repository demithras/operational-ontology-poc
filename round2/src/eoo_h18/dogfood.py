"""Dogfood: the real H15 lifecycle (preregister, freeze, run, attach evidence, derive verdict, supersede) through generic Actions
into a TEMP Git repository seeded read-only from the real repo; then the same repository is checked with the real ``git`` CLI."""
from __future__ import annotations

import json
import subprocess

from domains.project.seed_from_repo import H15_EVIDENCE_FILES

from .evaluators import registry
from .rig import EooRig, PRINCIPAL, trailers

EXP, HYP = "exp-h15-002", "H15"


def _git(repo, *a) -> str:
    r = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, timeout=120)
    return r.stdout.strip() if r.returncode == 0 else f"ERR:{r.stderr.strip()[:200]}"


def _draft(ops):
    out = []
    for o in ops:
        if o["op"] == "create" and o["type"] == "Hypothesis" and o["key"] == HYP:
            o = {**o, "props": {k: v for k, v in o["props"].items() if k != "freeze_hash"} | {"phase": "DRAFT"}}
        out.append(o)
    return out


def run_dogfood(reader, workdir=None) -> dict:
    rig = EooRig(workdir, reader=reader, h15_state="RUNNING")
    rig.evaluators = registry(reader, memo_h15=False)  # the real, un-memoised H15 evaluator
    st, ref = rig.store, "refs/heads/dogfood"
    st.import_ops(_draft(rig.base_ops), source="h15-replay", ref=ref, parent=rig.root)
    steps, n = [], [0]

    def act(name, action, inputs, expect_accept=True):
        n[0] += 1
        head0, e = st.head(ref), rig.engine(ref)
        rec = e.propose(action, inputs, PRINCIPAL, idempotency_key=f"dog-{n[0]}")
        head1 = st.head(ref)
        ok = rec["state"] == "RECONCILED_SUCCESS"
        steps.append({"step": name, "action": action, "state": rec["state"], "accepted": ok, "expected_accept": expect_accept,
                      "gate": next((g["gate"] for g in rec["gates"] if not g["passed"]), None), "head_moved": head1 != head0,
                      "exec": rec["exec"], "commit": head1 if ok else None, "base": head0})
        return rec
    e0 = rig.engine(ref)
    freeze = e0.call_function("compute_freeze_hash", {"experiment": EXP})
    th = json.loads(reader("protocol/thresholds.json"))[HYP]
    name = sorted(th)[0]
    thr = f"{HYP}.{name}"
    act("edit_threshold_while_draft", "edit_threshold", {"threshold": thr, "value": th[name]})  # same value: the frozen number is untouched
    act("preregister_with_computed_freeze_hash", "preregister_hypothesis", {"hypothesis": HYP, "freeze_hash": freeze})
    act("hostile_post_freeze_threshold_edit", "edit_threshold", {"threshold": thr, "value": 12345}, expect_accept=False)
    act("start_run", "start_run", {"hypothesis": HYP})
    for f in H15_EVIDENCE_FILES:
        act(f"attach_{f}", "attach_evidence", {"hypothesis": HYP, "evidence": f"{EXP}/{f}"})
    act("hostile_forced_verdict_input", "evaluate_hypothesis", {"hypothesis": HYP, "verdict": "SUPPORTED"}, expect_accept=False)
    act("evaluate_derives_verdict", "evaluate_hypothesis", {"hypothesis": HYP})
    act("supersede_test", "supersede_hypothesis", {"hypothesis": HYP, "successor": "H16"})
    final = st.state_at(st.head(ref))
    vals = [(k, r["props"]["value"]) for (t, k), r in final.objects.items() if t == "Verdict" and k.startswith(f"verdict-{HYP}-")]
    committed = json.loads(reader(f"experiments/h15/{EXP}/verdict.json"))["verdict"]
    return {"steps": steps, "freeze_hash": freeze, "derived_verdicts": vals, "committed_verdict": committed,
            "phase_final": final.objects[("Hypothesis", HYP)]["props"]["phase"],
            "reproducible": bool(vals) and vals[-1][1] == committed, "ref": ref, "repo": str(st.repo.path),
            "git_cli": git_cli_audit(rig, ref, steps)}


def git_cli_audit(rig, ref: str, steps: list) -> dict:
    repo, st = rig.store.repo.path, rig.store
    log = _git(repo, "log", "--format=%H", ref).split()
    accepted = [s for s in steps if s["accepted"]]
    msgs = {c: trailers(_git(repo, "log", "-1", "--format=%B", c)) for c in log}
    traced = [s for s in accepted if msgs.get(s["commit"], {}).get("EOO-Execution") == s["exec"] and msgs[s["commit"]].get("EOO-Action") == s["action"]]
    return {"fsck": _git(repo, "fsck", "--strict") == "" or "ok", "fsck_raw": _git(repo, "fsck", "--strict")[:200], "cli_commits_on_branch": len(log),
            "python_history_len": len(st.history(st.head(ref))), "expected_commits": len(accepted) + 2, "accepted_actions": len(accepted),
            "accepted_with_matching_commit_trailers": len(traced), "history_agrees": log == st.history(st.head(ref)),
            "import_commits": [c for c, t in msgs.items() if "EOO-Execution" not in t]}
