"""Per-variant H23 run: corpus -> evidence files (+ envelope). Official runs are produced by the orchestrator."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from r3_oracle import authority  # noqa: F401  (oracle version fingerprint below)
from r3_shared import evidence

from . import mutation, surface
from .analyze import analyze
from .corpus import DOMAINS, load_specs, new_env, run_corpus

ROUND3 = Path(__file__).resolve().parents[3].parent
FILES = ("adversarial-sequences.jsonl", "effect-oracle-diff.json", "identity-confusion-results.json",
         "direct-engine-backstop.json", "mutation-results.json", "surface-audit.json")


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


def run_variant(variant, vname: str, out: Path, exp_id: str, seed: int, sequences: int,
                mutation_sequences: int = 150, candidate_pkg: str | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    specs = load_specs()
    seq_path = out / FILES[0]
    with seq_path.open("w") as fh:
        for rec in run_corpus(variant, specs, sequences, seed):
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":"), default=str) + "\n")
    a = analyze(seq_path)
    rows = []
    for d in DOMAINS:
        env = new_env(variant, d, specs, f"audit-{d}")
        try:
            rows += surface.audit(env)
        finally:
            env.close()
    cc = a["class_counts"]
    _dump(out / FILES[1], {"calls": a["calls"], "unique_sequences": a["unique_sequences"], "class_counts": cc,
                           "rule_counts": a["rule_counts"], "op_coverage": a["op_coverage"],
                           "a_class_calls": a["a_class_calls"], "domains": a["domains"],
                           "legit_expected": a["legit_expected"], "legit_ok": a["legit_ok"],
                           "safe_progress_ratio": a["safe_progress_ratio"], "latency": a["legit_latency_ms"],
                           "flagged_sample": a["flagged_sample"]})
    _dump(out / FILES[2], {"identity_calls": a["identity_calls"], "identity_expansions": a["identity_expansions"],
                           "forbidden_effects": cc.get("forbidden_effect", 0)})
    _dump(out / FILES[3], {"tested": a["backstop_tested"], "passed": a["backstop_passed"], "rate": a["backstop_rate"],
                           "backstop_failures": cc.get("backstop_failure", 0)})
    _dump(out / FILES[5], {"rows": rows, "overexposure": surface.overexposure_count(rows)})
    _dump(out / FILES[4], mutation.prove(variant, specs, mutation_sequences))
    raw = {f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in FILES}
    env_ = evidence.build_envelope(
        experiment_id=exp_id, hypothesis_id="H23", git_commit=_git_head(),
        environment={"python": sys.version.split()[0], "platform": platform.platform(), "variant": vname},
        seed=seed, attack_class="A1,A2,A8", oracle_version=tree_sha("r3_oracle"),
        candidate_version=f"{vname}:{tree_sha(candidate_pkg) if candidate_pkg else 'test-fake'}",
        raw_observations={"evidence_sha256": raw, "sequences": sequences, "variant": vname})
    evidence.write_envelope(out / "envelope.json", env_)
    return {"analysis": a, "files": raw}
