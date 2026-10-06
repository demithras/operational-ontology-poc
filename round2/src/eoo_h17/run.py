"""Frozen H17 experiment run: builds the four evidence payloads and writes them (refuses to overwrite)."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from eoo_exp import provenance as prov
from eoo_exp.outdir import immutable_dir
from eoo_exp.util import ROOT, git, sha_file, sha_text

from . import agents, audits, baseline, mutants, tamper
from .drivers import new_driver
from .machine import CLASSES
from .runlib import new_sink, run_machine, unique

HID = "H17"
REQUIRED = ["state-machine-results.json", "effect-log-audit.json", "negative-action-results.json", "mutation-results.json"]
DOMAINS = ("manufacturing", "project")
HARNESS = [*sorted((ROOT / "src/eoo_h17").glob("*.py")), *sorted((ROOT / "src/eoo_exp").glob("*.py")),
           *sorted((ROOT / "oracles/h17").glob("*.py")), ROOT / "scripts/run_h17.py", ROOT / "scripts/evaluate_h17.py"]
FORBIDDEN_IMPORTS = ("eoo_engine", "eoo_toolchain", "domains")
STEP_COUNT = 14


def oracle_facts() -> dict:
    p = ROOT / "oracles/h17/model.py"
    imps = sorted({(n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
                   for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in
                   (n.names if isinstance(n, ast.Import) else [None])})
    return {"file": "oracles/h17/model.py", "sha256": sha_file(p), "imports": imps,
            "forbidden_imports": [i for i in imps if i in FORBIDDEN_IMPORTS]}


def engine_clean() -> dict:
    out = git("status", "--porcelain", "--", "round2/src/eoo_engine", "round2/domains", "round2/src/eoo_ir", "round2/protocol",
              "round2/hypotheses", "round2/experiments/h16")
    return {"paths_dirty": [ln[3:] for ln in out.splitlines()], "clean": not out.strip()}


def machine_corpus(seed: int, per_domain: int, chunk: int = 1500, max_chunks: int = 12) -> dict:
    res = {}
    for di, d in enumerate(DOMAINS):
        rows, executed, failures, i = {}, 0, [], 0
        while len(rows) < per_domain and i < max_chunks:
            n = min(chunk, max(40, int(1.4 * (per_domain - len(rows)))))
            sink = run_machine(d, seed * 1000 + di * 100 + i, n, step_count=STEP_COUNT, sink=new_sink())
            executed += len(sink["records"])
            failures += sink["failures"]
            for r in sink["records"]:
                if r["n_steps"] > 0:
                    rows.setdefault(r["sha"], r)
            i += 1
            if sink["failures"]:
                break
        res[d] = {"examples_executed": executed, "chunks": i, "unique": len(rows), "failures": failures, "cases": list(rows.values())}
    return res


def fn_audit(seed: int, n: int) -> dict:
    return {d: audits.function_only_rows(d, seed * 7 + k, n) for k, d in enumerate(DOMAINS)}


def agent_rows() -> dict:
    rows = []
    for d in DOMAINS:
        plan = [(n, "raw_write", f) for n, f in agents.RAW_ATTACKS] + [(n, "tamper", f) for n, f in tamper.TAMPER_BOTH]
        if d == "manufacturing":
            plan += [(n, "tamper", f) for n, f in tamper.TAMPER_MFG]
        plan += [(n, "disclosed_limit", f) for n, f in tamper.DISCLOSED]
        for n, c, f in plan:
            rows.append(agents.run_attack(new_driver(d, "std"), n, c, f))
    base = baseline.attacks()
    return {"agent_attacks": rows, "baseline_contextual": {
        "status": "CONTEXTUAL reference implementation written for this experiment, not measured industrial software, not a support condition",
        "model": "one generic operation type; every operation receives the same context (read + write); an 'effects' flag is metadata",
        "attacks": base, "violations": sum(r["violation"] for r in base),
        "reading": "The attack classes that depend on metadata honesty succeed against the single-operation model by construction; "
                   "this shows the attacks are not vacuous, it does not show the Engine is safe against them (see agent_attacks)."}}


def build(seed: int, per_domain: int, n_fn: int, n_ctrl: int, n_mut: int) -> tuple:
    sm = machine_corpus(seed, per_domain)
    fn = fn_audit(seed, n_fn)
    neg = {d: audits.negative_rows(d) for d in DOMAINS}
    mut = mutants.run_all(seed, n_ctrl, n_mut)
    cases = [dict(r) for d in DOMAINS for r in sm[d]["cases"]]
    corpus = sha_text(json.dumps(sorted(r["sha"] for r in cases)))
    p = {"state-machine-results.json": {
            "oracle": oracle_facts(), "engine_files": engine_clean(),
            "config": {"seed": seed, "per_domain_target": per_domain, "stateful_step_count": STEP_COUNT,
                       "sequence_classes_required": list(CLASSES), "domains": list(DOMAINS)},
            "per_domain": {d: {k: v for k, v in sm[d].items() if k != "cases"} for d in DOMAINS}, "cases": cases},
         "effect-log-audit.json": {"function_only_traces": [r for d in DOMAINS for r in fn[d]],
                                   "note": "per trace: EffectLog length+digest, canonical store hash and the external system's own state "
                                           "(adapter ground truth, independent of the EffectLog) before and after"},
         "negative-action-results.json": {"negative_cases": [r for d in DOMAINS for r in neg[d]], **agent_rows()},
         "mutation-results.json": mut}
    return p, {"corpus_hash": corpus, "unique": len({r["sha"] for r in cases})}


def run(seed: int, per_domain: int, out_root: Path, exp_id: str, n_fn: int = 1800, n_ctrl: int = 150, n_mut: int = 300) -> dict:
    pre = prov.preflight()
    with immutable_dir(out_root, exp_id) as tmp:
        payloads, info = build(seed, per_domain, n_fn, n_ctrl, n_mut)
        p = prov.provenance(pre, exp_id, HID, seed, info["corpus_hash"], HARNESS)
        for fn in REQUIRED:
            prov.write(tmp, fn, prov.wrap(p, fn[:-5], payloads[fn]))
    return info
