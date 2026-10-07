"""Per-variant H24 run: corpus -> evidence files (+ envelope). Official runs are produced by the orchestrator."""
from __future__ import annotations

import gzip
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from r3_harness.h23.corpus import load_specs
from r3_shared import evidence

from . import mutation
from .analyze import EXTRA, FILES, RACE_FILE, SEQ_FILE, TYPES, analyze
from .gen_race import run_race
from .gen_seq import run_sequence

ROUND3 = Path(__file__).resolve().parents[3]
PROT = ROUND3 / "spec" / "protections" / "PROT-H24.md"
ORACLE_FILES = ("authority_v2.py", "scope_v2.py", "judge_v2.py", "judge_calls.py", "logreplay.py", "ops_model.py",
                "authority.py")


def tree_sha(pkg: str) -> str:
    h = hashlib.sha256()
    for f in sorted((ROUND3 / "src" / pkg).rglob("*.py")):
        h.update(f.relative_to(ROUND3).as_posix().encode() + f.read_bytes())
    return h.hexdigest()


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "-C", str(ROUND3), "rev-parse", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "0000000"


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")


def _safe(fn, *a, kind: str, i: int, domain: str):
    """A variant that breaks the harness path is a recorded `unsupported` case (INCONCLUSIVE), never a crashed run."""
    try:
        return fn(*a)
    except Exception as exc:  # noqa: BLE001
        return {"id": f"{kind}-{i}", "domain": domain, "digest": f"error-{kind}-{i}-{type(exc).__name__}", "calls": [],
                "case_classes": ["unsupported"], "classes": ["unsupported"], "match": False, "type": "ERR",
                "overlap": False, "order": None, "executed": False, "error": f"{type(exc).__name__}: {exc}"}


def run_variant(factory, vname: str, out: Path, exp_id: str, seed: int, sequences: int, races: int,
                mutation_sequences: int = 60, mutation_races: int = 60, candidate_pkg: str | None = None) -> dict:
    """`factory(mutants) -> Variant` (registry.load_variant for real variants). Baseline = factory(())."""
    out.mkdir(parents=True, exist_ok=True)
    variant, specs = factory(()), load_specs()
    domains = ("manufacturing", "project")
    with gzip.open(out / SEQ_FILE, "wt") as fh:
        for i in range(sequences):
            rec = _safe(run_sequence, variant, specs, seed, i, kind="seq", i=i, domain=domains[i % 2])
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), default=str) + "\n")
    n_total = -(-races * len(TYPES) // (len(TYPES) - 1))  # `races` concurrent cases + the SEQ controls
    cases = [_safe(run_race, variant, specs, seed, j, TYPES[j % len(TYPES)], kind="race", i=j, domain=domains[j % 2])
             for j in range(n_total)]
    _dump(out / RACE_FILE, {"seed": seed, "cases": cases})
    mres = mutation.prove(factory, specs, mutation_sequences, mutation_races, seed)
    return write_evidence(out, vname, exp_id, seed, sequences, races, mres, candidate_pkg)


def write_evidence(out: Path, vname: str, exp_id: str, seed: int, sequences: int, races: int, mutation_results: dict,
                   candidate_pkg: str | None = None) -> dict:
    """Everything after the raw rows exist (authority-sequences.jsonl.gz, revocation-races.json): summaries + envelope."""
    a = analyze(out)
    attempts = a.pop("attempts")
    _dump(out / FILES[0], {**{k: v for k, v in a.items() if k != "races"}, "seed": seed,
                           "sequences_file": SEQ_FILE, "sequences_sha256": sha_file(out / SEQ_FILE)})
    _dump(out / FILES[2], {"attempts_columns": ["case", "n", "intent", "depth", "status", "committed", "oracle_verdict",
                                                "oracle_reason", "classes"], "attempts": attempts,
                           "scope_amplification": a["class_counts"].get("scope_amplification", 0),
                           "cycle_grant": a["class_counts"].get("cycle_grant", 0)})
    _dump(out / FILES[3], {"progress": a["progress"], "races": a["races"], "latency_ms": a["latency_ms"],
                           "floors": {"unaffected_legit_progress": 1.0, "overlap_fraction": 0.5, "effect_first_rv": 1}})
    _dump(out / FILES[4], mutation_results)
    from .evaluator import evaluator_sha256
    raw = {f: sha_file(out / f) for f in FILES + EXTRA}
    env_ = evidence.build_envelope(
        experiment_id=exp_id, hypothesis_id="H24", git_commit=_git_head(),
        environment={"python": sys.version.split()[0], "platform": platform.platform(), "variant": vname},
        seed=seed, attack_class="A3,A4,A8", oracle_version=tree_sha("r3_oracle"),
        candidate_version=f"{vname}:{tree_sha(candidate_pkg) if candidate_pkg else 'test-fake'}",
        raw_observations={"evidence_sha256": raw, "sequences": sequences, "races": races, "variant": vname,
                          "prot_h24_sha256": sha_file(PROT), "evaluator_sha256": evaluator_sha256()})
    evidence.write_envelope(out / "envelope.json", env_)
    return {"analysis": a, "files": raw}
