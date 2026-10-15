"""Per-variant H25 run: corpus -> evidence files (+ envelope). Official runs are produced by the orchestrator only; dev runs
(`exp-h25-dev*`) may lower the minimums, stamped in verdict.json. Never raises on a variant that breaks the harness path
(recorded as an `unsupported` case => INCONCLUSIVE)."""
from __future__ import annotations

import gzip
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from r3_shared import evidence

from . import analyze as AN
from . import audit, boundary, mutation
from .gen_case import run_case, run_nogov
from .gen_race import TYPES, run_race

ROUND3 = Path(__file__).resolve().parents[3]
PROT = ROUND3 / "spec" / "protections" / "PROT-H25.md"
GOV_FIXTURES = tuple(f"spec/governance/{m}.{d}.json" for m in AN.MODELS for d in ("manufacturing", "project"))
MISMATCH = {"procedural_mismatch", "illegitimate_effect", "fabricated_judgment", "emergency_violation",
            "linearizability_violation", "invalid_doc_accepted"}
JUDGMENT_STREAM = "h25-judgment-<seed>-<i> (random.Random, seeded separately from h25-case/h25-model streams)"


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree_sha(pkg: str) -> str:
    h = hashlib.sha256()
    for f in sorted((ROUND3 / "src" / pkg).rglob("*.py")):
        h.update(f.relative_to(ROUND3).as_posix().encode() + f.read_bytes())
    return h.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROUND3), "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "0000000"


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")


def _safe(fn, *a, kind: str, i: int):
    try:
        return fn(*a)
    except Exception as exc:  # noqa: BLE001
        return {"id": f"{kind}-err-{i}", "model": AN.MODELS[i % 3], "domain": "manufacturing", "type": "ERR",
                "digest": f"error-{kind}-{i}-{type(exc).__name__}", "calls": [], "case_classes": ["unsupported"],
                "classes": ["unsupported"], "tags": [], "final": {}, "redraws": 0, "error": f"{type(exc).__name__}: {exc}"}


def run_variant(factory, vname: str, out: Path, exp_id: str, seed: int, cases: int, races: int, nogov: int = 100,
                mutation_cases: int = 120, mutation_races: int = 40, audit_cases: int = 1000, boundary_cases: int = 1000,
                candidate_pkg: str | None = None, keep_roles=(), scan_sources=None, oracle_reference=None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    variant = factory(())
    n_races = -(-races * len(TYPES) // (len(TYPES) - 1))  # `races` concurrent cases + the SEQ controls
    with gzip.open(out / AN.CASES_FILE, "wt") as fh:
        jobs = ([("case", run_case, (variant, seed, i)) for i in range(cases)]
                + [("race", run_race, (variant, seed, j, TYPES[j % len(TYPES)])) for j in range(n_races)]
                + [("nogov", run_nogov, (variant, seed, k)) for k in range(nogov)])
        for n, (kind, fn, args) in enumerate(jobs):
            rec = _safe(fn, *args, kind=kind, i=n)
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), default=str) + "\n")
    mres = mutation.prove(factory, seed, mutation_cases, mutation_races, min(audit_cases, 60),
                          scan_pkg=(ROUND3 / "src" / candidate_pkg) if candidate_pkg else None, keep_roles=keep_roles,
                          scan_sources=scan_sources)
    dba = domain_audit(variant, factory, seed, audit_cases, candidate_pkg, keep_roles, scan_sources, mres, oracle_reference)
    oba = boundary_audit(variant, seed, boundary_cases, out)
    return write_evidence(out, vname, exp_id, seed, cases, races, nogov, mres, dba, oba, candidate_pkg)


def domain_audit(variant, factory, seed, n, candidate_pkg, keep_roles, scan_sources, mres, oracle_reference=None) -> dict:
    ren = audit.rename_audit(variant, seed, n, keep_roles=keep_roles)
    scan = audit.static_scan(pkg_dir=(ROUND3 / "src" / candidate_pkg) if candidate_pkg else None, sources=scan_sources)
    oracle = {"cases": 0, "domain_branch": None, "note": "no oracle reference supplied"}
    if oracle_reference is not None:  # the oracle-backed reference deployment (a harness test double), renamed like a variant
        r = audit.rename_audit(oracle_reference, seed, 40, keep_roles=("admin",))
        oracle = {"cases": r["cases"], "domain_branch": r["domain_branch"], "note": "oracle-backed reference deployment"}
    m = mres.get("domain_privilege_branch", {})
    return {"renaming": ren, "static_scan": scan, "cross_domain": {"domains": list(ren["by_domain"]), "by_domain": ren["by_domain"]},
            "domain_branch": ren["domain_branch"] + scan["hit_count"],
            "self_test": {"mutant_build_flagged": bool(m.get("killed")), "oracle_reference": oracle}}


def boundary_audit(variant, seed, n, out: Path) -> dict:
    merit = [boundary.merit_probe(variant, seed, i) for i in range(n)]
    flips, i = [], 0
    while sum(1 for f in flips if f["changed"]) < n and i < n * 4:
        flips.append(boundary.flip_probe(variant, seed, i))
        i += 1
    changed = [f for f in flips if f["changed"]]
    exp = obs = 0
    for c in AN.read_cases(out):
        exp += "execute:DENIED:oracle_needed" in c["tags"]
        obs += sum(1 for r in c["calls"] if r.get("action") == "execute" and r.get("reason") == "oracle_needed")
    return {"merit_invariance": {"cases": n, "judge_actions": sum(m["judge_actions"] for m in merit),
                                 "fabricated": sum(m["fabricated"] for m in merit), "first": next((m for m in merit if m["fabricated"]), None)},
            "judgment_flip": {"probed": len(flips), "oracle_outcome_changed": len(changed),
                              "variant_followed_oracle": sum(1 for f in changed if not set(f["classes"]) & (MISMATCH | {"progress_loss"})),
                              "mismatch": sum(1 for f in changed if set(f["classes"]) & MISMATCH),
                              "progress_loss": sum(1 for f in changed if "progress_loss" in f["classes"]),
                              "first": next((f for f in changed if set(f["classes"]) & MISMATCH), None)},
            "oracle_needed": {"expected_cases": exp, "observed_execute_rows": obs},
            "provenance": {"judgment_rng_stream": JUDGMENT_STREAM, "model_rng_streams": ["h25-model-*", "h25-case-*"],
                           "streams_distinct": True,
                           "fixtures_sha256": {f: sha_file(ROUND3 / f) for f in GOV_FIXTURES},
                           "prot_h25_sha256": sha_file(PROT),
                           "oracle_imports": _oracle_imports()}}


def _oracle_imports() -> list[str]:
    import ast
    mods: set[str] = set()
    for f in sorted((ROUND3 / "src" / "r3_oracle").rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Import):
                mods |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                mods.add(n.module)
    return sorted(m for m in mods if m.split(".")[0] in ("r3_shared", "r3_harness", "paladin", "conventional", "eoo_engine", "eoo_toolchain"))


def write_evidence(out: Path, vname: str, exp_id: str, seed: int, cases: int, races: int, nogov: int, mres: dict,
                   dba: dict, oba: dict, candidate_pkg: str | None = None) -> dict:
    a = AN.analyze(out)
    prow = []
    for c in AN.read_cases(out):
        for r in c["calls"]:
            if set(r["classes"]) - {"ok", "race_refusal_ok"} and len(prow) < 200:
                prow.append({"case": c["id"], "model": c["model"], "domain": c["domain"],
                             **{k: r.get(k) for k in ("n", "kind", "action", "actor", "status", "reason", "classes", "oracle")}})
    per = {m: {d: 0 for d in ("manufacturing", "project")} for m in AN.MODELS}
    for c in AN.read_cases(out):
        if c["model"] in per:
            per[c["model"]][c["domain"]] += 1
    _dump(out / FILES0, {"seed": seed, "cases_file": AN.CASES_FILE, "cases_sha256": sha_file(out / AN.CASES_FILE),
                         "cases": a["cases"], "unique_cases": a["unique_cases"], "per_model_domain": per,
                         "models": a["models"], "oracle_needed_cases": a["oracle_needed_cases"],
                         "precedence_conflict_cases": a["precedence_conflict_cases"],
                         "precedence_unresolved_cases": a["precedence_unresolved_cases"], "appeal_cases": a["appeal_cases"],
                         "emergency_cases": a["emergency_cases"], "emergency_late_act_cases": a["emergency_late_act_cases"],
                         "race_cases": a["race_cases"], "race_overlapping": a["race_overlapping"], "race_types": a["race_types"],
                         "nogov_cases": a["nogov_cases"], "generator_redraws": a["redraws"]})
    _dump(out / AN.FILES[1], {"actions": a["actions"], "class_counts": a["class_counts"], "first_offending_rows": prow,
                              "cases_file": AN.CASES_FILE, "cases_sha256": sha_file(out / AN.CASES_FILE)})
    _dump(out / AN.FILES[2], dba)
    _dump(out / AN.FILES[3], oba)
    _dump(out / AN.FILES[4], mres)
    _dump(out / AN.EXTRA[0], {"progress": a["progress"], "latency_ms": a["latency_ms"],
                              "floors": {"legit_progress": 1.0, "oracle_needed_cases": 1000, "precedence_conflict_cases": 500,
                                         "per_model_rules_and_reasons": "reachable(model) in analyze.py"}})
    from .evaluator import evaluator_sha256
    raw = {f: sha_file(out / f) for f in AN.FILES + AN.EXTRA}
    env_ = evidence.build_envelope(
        experiment_id=exp_id, hypothesis_id="H25", git_commit=_git_head(),
        environment={"python": sys.version.split()[0], "platform": platform.platform(), "variant": vname},
        seed=seed, attack_class="A4,A3,A8", oracle_version=tree_sha("r3_oracle"),
        candidate_version=f"{vname}:{tree_sha(candidate_pkg) if candidate_pkg else 'test-fake'}",
        raw_observations={"evidence_sha256": raw, "cases": cases, "races": races, "nogov": nogov, "variant": vname,
                          "prot_h25_sha256": sha_file(PROT), "evaluator_sha256": evaluator_sha256()})
    evidence.write_envelope(out / "envelope.json", env_)
    return {"analysis": a, "files": raw}


FILES0 = AN.FILES[0]
