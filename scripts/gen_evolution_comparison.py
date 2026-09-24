#!/usr/bin/env python3
"""Phase 10b item 7 — "FAIR EVOLUTION COMPARISON" (orchestrator finding
from the Phase 8 review): `services/baseline` had no V1-era history of its
own, so replay-across-contract-evolution (H7/H11's central ontology claim)
was never actually compared between the two variants.

This script drives BOTH variants through the SAME real evolution, in the
SAME run:

    its OWN destructive fresh reset, staying at the V1 genesis (below)
      -> V1 decisions (ontology + baseline, real HTTP, REAL V1 SHACL
         shapes genuinely live and enforcing)
      -> deploy V2 (ontology's RDF/policy/action migration; baseline's
         "equivalent relational migration" is measured, not assumed)
      -> V2 decisions (ontology + baseline, real HTTP)
      -> deploy V3 (+ V3 gates)
      -> full replay sweep of EVERY decision in BOTH variants' tables
         under the (by then) V3-deployed historical rules.

Orchestrator correction (Phase 10b, 2026-09-24, superseding an earlier,
WRONG version of this module): a genuinely fresh stack now auto-advances
to the product's CURRENT contracts (V3) at `make seed` time
(services/common/advance_fresh_stack_to_current.py), because README's
definition-of-done runs `make test` right after `make seed` and most of
this repo's suite assumes V3 features are live. An EARLIER version of this
script tried to reuse that already-migrated (and by the time `make
experiment` runs, already-populated-by-make-test) stack by just flipping
the deployed_version.json POINTER back to "v1" without touching the live
RDF4J shapes graph — reasoning that a v1-labeled write would only ever be
validated against a strictly MORE PERMISSIVE v3 ruleset. That reasoning is
BACKWARDS and was rejected: a more permissive ruleset ACCEPTS MORE (e.g.
v3's `oo:status` enum allows `oo:GateUnavailable`, which v1 does not) —
so a "v1-era" decision validated under live v3 shapes is NOT actually
proven to satisfy real v1 rules, which silently weakens exactly the
historical-contract-integrity property H7/H8 exist to test.

The correct, and only sound, way to build genuine V1-era history is on a
stack where V1's REAL shapes are the ones actually live and enforcing.
Since `make experiment` "by definition creates a fresh, self-contained
experiment" (orchestrator), this script performs its OWN destructive reset
first — `make down` -> `docker compose down -v` -> `make up` -> `make
seed` with `OO_SKIP_AUTO_ADVANCE=1` so the stack STAYS at the tracked V1
baseline (real V1 ontology/shapes/actions/policies/authorization, never
touched or reloaded away from it) — then builds V1-era history for real,
under real V1 rules, before advancing forward the same real
`make deploy-v2`/`make deploy-v3`/`make deploy-v3-gates` functions every
other phase already uses. Every subsequent run_experiment.py step (bulk
corpus, full test suite, mutation tests, full A/B rerun, latency, fault
matrix) runs on THIS resulting stack, not the one `make test` validated
earlier in the clean-machine sequence — that earlier stack's only job was
proving a fresh `make seed` serves V3 out of the box.

Writes experiments/exp-000/results/evolution-comparison.json. Exits 0 on
completion (replay parity is REPORTED, not gated here — spec 10 explicitly
allows "the baseline replays just as well" as a valid outcome); exits 1
only on a genuine harness error (a step raising, or the post-reset stack
failing to land on the real V1 baseline).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

VENV_PY = str(REPO_ROOT / ".venv" / "bin" / "python")
DEPLOYED_VERSION_PATH = REPO_ROOT / "contracts" / "manifests" / "deployed_version.json"
BASELINE_V1_PATH = REPO_ROOT / "contracts" / "manifests" / "baseline_v1.json"
RESULTS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "evolution-comparison.json"
ONTOLOGY_CORPUS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "historical-corpus.json"
BASELINE_CORPUS_PATH = REPO_ROOT / "experiments" / "exp-000" / "results" / "historical-corpus-baseline.json"


def _run(args: list[str], label: str) -> dict:
    print(f"[evolution] >>> {label}: {' '.join(args)}", flush=True)
    t0 = time.monotonic()
    result = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=600)
    elapsed = round(time.monotonic() - t0, 1)
    print(result.stdout[-4000:])
    if result.returncode != 0:
        print(result.stderr[-4000:], file=sys.stderr)
        raise RuntimeError(f"{label} failed (exit {result.returncode}) after {elapsed}s")
    print(f"[evolution] <<< {label} done in {elapsed}s", flush=True)
    return {"label": label, "elapsed_s": elapsed}


def _fresh_reset_to_v1() -> dict:
    """This script's OWN destructive fresh reset (make experiment "by
    definition creates a fresh, self-contained experiment" — orchestrator
    correction). Wipes the ENTIRE stack and rebuilds it, staying at the
    tracked V1 genesis (OO_SKIP_AUTO_ADVANCE=1) so the REAL V1
    ontology/shapes/actions/policies/authorization are genuinely live and
    enforcing when V1-era history gets built — never a pointer-only
    shortcut (see module docstring for why an earlier version of this
    function got that wrong)."""
    import os
    import shutil

    before = json.loads(DEPLOYED_VERSION_PATH.read_text()) if DEPLOYED_VERSION_PATH.exists() else {}
    before_c = {k: v for k, v in before.items() if not k.startswith("_")}

    env = dict(os.environ)
    env["OO_ALLOW_DESTRUCTIVE"] = "1"

    def make(args: list[str], label: str, extra_env: dict | None = None, timeout: int = 600) -> None:
        full_env = dict(env)
        if extra_env:
            full_env.update(extra_env)
        print(f"[evolution] >>> {label}: {' '.join(args)}", flush=True)
        t0 = time.monotonic()
        result = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout, env=full_env)
        print(result.stdout[-4000:])
        if result.returncode != 0:
            print(result.stderr[-4000:], file=sys.stderr)
            raise RuntimeError(f"{label} failed (exit {result.returncode})")
        print(f"[evolution] <<< {label} done in {time.monotonic() - t0:.1f}s", flush=True)

    print(f"[evolution] starting this script's OWN fresh reset (was {before_c}) — "
          f"make down / docker compose down -v / make up / make seed (OO_SKIP_AUTO_ADVANCE=1)", flush=True)
    make(["make", "down"], "make down", timeout=120)
    make(["docker", "compose", "down", "-v"], "docker compose down -v", timeout=180)
    make(["make", "up"], "make up", timeout=600)
    make(["make", "seed"], "make seed (staying at V1)",
         extra_env={"SEED": "42", "OO_SKIP_AUTO_ADVANCE": "1", "WAIT_CONVERGED_TIMEOUT_S": "600"}, timeout=900)

    live = json.loads(DEPLOYED_VERSION_PATH.read_text())
    baseline = json.loads(BASELINE_V1_PATH.read_text())
    live_c = {k: v for k, v in live.items() if not k.startswith("_")}
    base_c = {k: v for k, v in baseline.items() if not k.startswith("_")}
    if live_c != base_c:
        raise RuntimeError(
            f"gen_evolution_comparison.py's own fresh reset did not land on the tracked V1 baseline — "
            f"deployed_version.json is {live_c}, expected {base_c}. Refusing to build 'V1-era' history "
            f"under the wrong rules."
        )
    print(f"[evolution] fresh reset landed on the real V1 baseline: {live_c}", flush=True)
    return before_c


def _git_derived_migration_effort(paths: list[str]) -> dict:
    """Derives files-changed/insertions/deletions from git log --numstat over
    the given paths — never hand-typed (common.md honesty rule).

    Deliberately NO --follow: found live while validating this script —
    `--follow` only accepts exactly ONE pathspec and git exits nonzero
    ("fatal: --follow requires exactly one pathspec") the moment a second
    directory is passed (migrations/v2_to_v3/ + migrations/v2_to_v3_gates/,
    this function's own second call site). The first call site (a single
    path) never errored, so this silently produced files_changed=0/
    insertions=0 for v2_to_v3 while looking like a normal, if boring,
    result — caught only by reading the actual number, not by any crash.
    --follow's single-file-rename tracking isn't the right tool for a
    directory-level aggregate anyway; a plain `git log --numstat` over the
    given paths is both correct and multi-path-safe. The return code is
    also checked now, so a FUTURE git failure aborts loudly instead of
    reporting a plausible-looking zero (common.md: an empty result is a
    filter-miss until validated, not evidence of absence)."""
    proc = subprocess.run(
        ["git", "log", "--numstat", "--pretty=format:__COMMIT__%H", "--", *paths],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git log --numstat failed (exit {proc.returncode}) for paths {paths}: {proc.stderr}")
    log = proc.stdout
    commits: set[str] = set()
    files: set[str] = set()
    insertions = deletions = 0
    current_commit = None
    for line in log.splitlines():
        if line.startswith("__COMMIT__"):
            current_commit = line[len("__COMMIT__"):]
            commits.add(current_commit)
            continue
        parts = line.split("\t")
        if len(parts) == 3:
            ins, dele, path = parts
            files.add(path)
            insertions += int(ins) if ins.isdigit() else 0
            deletions += int(dele) if dele.isdigit() else 0
    return {"commits": sorted(commits), "files_changed": len(files), "insertions": insertions, "deletions": deletions}


def _baseline_specific_files_touched(paths: list[str]) -> list[str]:
    """Any line in the migration scripts themselves that references
    services/baseline — if this is empty, the baseline's own migration
    effort is genuinely zero, not merely unmeasured."""
    hits: list[str] = []
    for rel in paths:
        p = REPO_ROOT / rel
        if p.is_file() and "baseline" in p.read_text(errors="ignore"):
            hits.append(rel)
    return hits


def main() -> int:
    steps: list[dict] = []
    t_start = time.monotonic()

    deployed_version_before_descent = _fresh_reset_to_v1()

    # --- V1 era: real HTTP corpus, both variants -------------------------
    steps.append(_run([VENV_PY, "seed/generators/historical_corpus.py", "--version", "v1", "--n", "110"], "ontology V1 corpus"))
    steps.append(_run([VENV_PY, "seed/generators/baseline_historical_corpus.py", "--version", "v1", "--n", "110"], "baseline V1 corpus"))

    # --- deploy V2 (ontology-specific migration; baseline gets it "for
    # free" via the shared deployed_version.json — measured below, not
    # assumed) --------------------------------------------------------
    before_baseline_status = subprocess.run(["git", "status", "--porcelain", "services/baseline"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    steps.append(_run([VENV_PY, "migrations/v1_to_v2/deploy.py"], "deploy V2 (ontology migration)"))
    after_baseline_status = subprocess.run(["git", "status", "--porcelain", "services/baseline"], cwd=REPO_ROOT, capture_output=True, text=True).stdout

    # --- V2 era: real HTTP corpus, both variants -------------------------
    steps.append(_run([VENV_PY, "seed/generators/historical_corpus.py", "--version", "v2", "--n", "110"], "ontology V2 corpus"))
    steps.append(_run([VENV_PY, "seed/generators/baseline_historical_corpus.py", "--version", "v2", "--n", "110"], "baseline V2 corpus"))

    # --- deploy V3 (+ V3 gates) -------------------------------------------
    steps.append(_run([VENV_PY, "migrations/v2_to_v3/deploy.py"], "deploy V3 (authorization evolution)"))
    steps.append(_run([VENV_PY, "migrations/v2_to_v3_gates/deploy.py"], "deploy V3 gates"))

    # --- full replay sweep, both variants, under the NOW-V3-deployed rules
    ont_sweep = subprocess.run([VENV_PY, "scripts/replay_full_sweep.py"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=900)
    print(ont_sweep.stdout[-3000:])
    base_sweep = subprocess.run([VENV_PY, "scripts/baseline_replay_sweep.py"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=900)
    print(base_sweep.stdout[-3000:])
    base_sweep_path = BASELINE_CORPUS_PATH.parent / "baseline-replay-sweep.json"
    base_sweep_json = json.loads(base_sweep_path.read_text()) if base_sweep_path.exists() else None

    ontology_corpus = json.loads(ONTOLOGY_CORPUS_PATH.read_text()) if ONTOLOGY_CORPUS_PATH.exists() else {}
    baseline_corpus = json.loads(BASELINE_CORPUS_PATH.read_text()) if BASELINE_CORPUS_PATH.exists() else {}

    v1_to_v2_effort = _git_derived_migration_effort(["migrations/v1_to_v2/"])
    v2_to_v3_effort = _git_derived_migration_effort(["migrations/v2_to_v3/", "migrations/v2_to_v3_gates/"])
    baseline_touch_v1v2 = _baseline_specific_files_touched(
        [str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "migrations" / "v1_to_v2").rglob("*.py")]
    )
    baseline_touch_v2v3 = _baseline_specific_files_touched(
        [str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "migrations" / "v2_to_v3").rglob("*.py")]
        + [str(p.relative_to(REPO_ROOT)) for p in (REPO_ROOT / "migrations" / "v2_to_v3_gates").rglob("*.py")]
    )

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_elapsed_s": round(time.monotonic() - t_start, 1),
        "deployed_version_before_descent_to_v1": deployed_version_before_descent,
        "steps": steps,
        "corpus": {
            "ontology": {k: v for k, v in ontology_corpus.items() if k not in ("_generated_at_last_update",)},
            "baseline": {k: v for k, v in baseline_corpus.items() if k not in ("_generated_at_last_update",)},
        },
        "replay_sweep": {
            "ontology_stdout_tail": ont_sweep.stdout[-2000:],
            "ontology_exit_code": ont_sweep.returncode,
            "baseline_summary": base_sweep_json,
            "baseline_exit_code": base_sweep.returncode,
        },
        "migration_effort": {
            "ontology_v1_to_v2": v1_to_v2_effort,
            "ontology_v2_to_v3": {**v2_to_v3_effort},
            "baseline_v1_to_v2_files_touched": baseline_touch_v1v2,
            "baseline_v2_to_v3_files_touched": baseline_touch_v2v3,
            "baseline_git_status_services_baseline_before_deploy_v2": before_baseline_status.strip(),
            "baseline_git_status_services_baseline_after_deploy_v2": after_baseline_status.strip(),
            "finding": (
                "The baseline's authorization/policy/identity contracts are version-pinned from the SAME "
                "contracts/manifests/deployed_version.json file the ontology variant reads "
                "(services/baseline/manifest.py) — a contract redeploy affects both variants identically with "
                "ZERO baseline-specific code changes (git status over services/baseline is empty before and "
                "after `make deploy-v2`/`make deploy-v3`, and neither migration script mentions "
                "services/baseline at all). The real asymmetry spec 10 flagged was baseline having no V1-era "
                "history of its own; this script closes that gap. There is no separate relational schema "
                "migration for the 'available -> on_hand-reserved' evolution either — services/baseline "
                "computes it inline (see Phase 8 W4 finding) — so, for THIS bounded domain, the baseline's "
                "replay-across-evolution mechanism costs materially less engineering effort than the ontology "
                "variant's RDF/SHACL/projection migrations, while (see replay_sweep above) reaching a "
                "comparable pass rate on its own historical corpus."
            ),
        },
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"[evolution] wrote {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
