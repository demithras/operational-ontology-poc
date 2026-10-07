"""Per-variant H27 run -> evidence files + envelope. Runs INSIDE scripts/run_sandboxed.sh (anchor outside the sandbox).
Anchor close / E2 / E5 / envelope are completed by `finalize` after the anchor was closed."""
from __future__ import annotations

import hashlib
import inspect
import json
import platform
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from r3_shared import evidence
from r3_shared.anchor import AnchorClient

from . import audit, corpus, mutation

ROUND3 = Path(__file__).resolve().parents[3]
FILES = ("provenance-bundles.jsonl", "tamper-mutation-results.json", "historical-replay.json", "anchor-audit.json",
         "mutation-results.json")
EXTRA = ("expected-bindings.jsonl",)
CANON_SHA = hashlib.sha256(inspect.getsource(evidence.canonical_bytes).encode()).hexdigest()


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


def _lines(path: Path, rows) -> None:
    with path.open("w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":"), default=str) + "\n")


def run_variant(factory, vname: str, out: Path, exp_id: str, seed: int, anchor_sock: str, anchor_dir: str, *,
                per_domain: int = 300, tamper_cases: int = 5000, controls: int = 1000, decisions=(5, 30),
                mutation_bases: int = mutation.SUB_BASES, mutation_cases: int = mutation.SUB_CASES) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    anchor = AnchorClient(anchor_sock)
    a = audit.probe(anchor_dir, anchor_sock)
    _dump(out / FILES[3], a)
    work = tempfile.mkdtemp(prefix="h27-run-")
    variant = factory(())
    try:
        bases = corpus.build_bases(variant, anchor, work, seed, per_domain, decisions)
        _lines(out / EXTRA[0], ({"base": b.id, "domain": b.domain, "seq": r["seq"], "decision": r["decision"],
                                 "artifacts": r["artifacts"]} for b in bases for r in b.decisions))
        exp_sha = hashlib.sha256((out / EXTRA[0]).read_bytes()).hexdigest()  # hashed BEFORE any tampering
        _lines(out / FILES[0], (row for b in bases for row in b.bundles))
        stats: dict = {}
        tcases = list(corpus.run_effective(variant, anchor, bases, work, seed, tamper_cases, stats))
        ccases = list(corpus.run_clean(variant, anchor, bases, work, seed, controls))
        base_div = [d for b in bases for d in b.divergences]
        unanch = [u for b in bases for u in b.unanchored]
        _dump(out / FILES[1], {"seed": seed, "bases": len(bases), "base_domains": {d: sum(b.domain == d for b in bases) for d in corpus.DOMAINS},
                               "attempt_stats": stats, "cases": tcases, "binding_divergences": base_div, "unanchored_acks": unanch})
        _dump(out / FILES[2], {"controls": [{k: c[k] for k in ("case", "base", "domain", "n", "replays", "classes_hit", "replay_ms")}
                                           for c in ccases], "binding_divergences": base_div})
        _dump(out / FILES[4], {"cases_per_mutant": mutation_cases, **mutation.prove(factory, anchor, seed, mutation_bases, mutation_cases)})
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"expected_bindings_sha256": exp_sha, "seed": seed, "variant": vname}


def seal(out: Path, exp_id: str, vname: str, seed: int, pre: dict, candidate_pkg: str | None) -> None:
    """Write envelope.json over every evidence file (called by finalize after the anchor audit is complete)."""
    raw = {f: hashlib.sha256((out / f).read_bytes()).hexdigest() for f in FILES + EXTRA}
    env = evidence.build_envelope(
        experiment_id=exp_id, hypothesis_id="H27", git_commit=_git_head(),
        environment={"python": sys.version.split()[0], "platform": platform.platform(), "variant": vname},
        seed=seed, attack_class="A6", oracle_version=tree_sha("r3_oracle"),
        candidate_version=f"{vname}:{tree_sha(candidate_pkg) if candidate_pkg else 'test-fake'}",
        raw_observations={"evidence_sha256": raw, "variant": vname, "expected_bindings_sha256": pre["expected_bindings_sha256"],
                          "canonical_bytes_source_sha256": CANON_SHA,
                          "prot_h27_sha256": hashlib.sha256((ROUND3 / "spec/protections/PROT-H27.md").read_bytes()).hexdigest()})
    evidence.write_envelope(out / "envelope.json", env)
