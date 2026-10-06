"""Frozen-protocol H20 run: builds the five evidence payloads and writes them (refuses to overwrite)."""
from __future__ import annotations

import inspect
import json
from collections import Counter
from pathlib import Path

from eoo_engine import DISPATCH_TABLE, ENGINE_VERSION
from eoo_exp import provenance as prov
from eoo_exp.outdir import immutable_dir
from eoo_exp.util import ROOT, REPO, git, load_oracle, sha_file, sha_text

from . import adapter_dynamic, adapter_static, alias, loc, mutants, payloads, provenance_writes, static_audit, synth, synth_run, workloads
from .closure import closure, domain_roots
from .trace import Tracer, profiling_dispatch

HID = "H20"
REQUIRED = ["engine-static-audit.json", "dispatch-traces.json", "adapter-responsibility-audit.json",
            "synthetic-resource-results.json", "mutation-results.json"]
HARNESS = [*sorted((ROOT / "src/eoo_h20").glob("*.py")), *sorted((ROOT / "src/eoo_exp").glob("*.py")),
           *sorted((ROOT / "oracles/h20").glob("*.py")), ROOT / "scripts/run_h20.py", ROOT / "scripts/evaluate_h20.py"]
FORBIDDEN_IMPORTS = ("eoo_engine", "eoo_toolchain", "domains")
ENGINE_DIRS = ("src/eoo_engine", "src/eoo_engine_git")
PROTECTED = ["round2/src/eoo_engine", "round2/src/eoo_engine_git", "round2/domains", "round2/src/eoo_ir", "round2/protocol", "round2/hypotheses"]
BINDING_SIDE = ("domains/",)
HARNESS_SIDE = ("src/eoo_h20/", "src/eoo_h17/", "src/eoo_h18/", "src/eoo_exp/", "src/eoo_h16/", "src/eoo_h15/", "oracles/", "tests/", "scripts/")


def engine_hashes() -> dict:
    return {p.relative_to(ROOT).as_posix(): sha_file(p) for d in ENGINE_DIRS for p in sorted((ROOT / d).rglob("*.py"))
            if "__pycache__" not in p.parts}


def dispatch_fingerprint() -> dict:
    return {k: {"handler": type(h).__qualname__, "ops": sorted(h.ops), "source_sha256": sha_text(inspect.getsource(type(h)))}
            for k, h in DISPATCH_TABLE.items()}


def candidate() -> dict:
    tag = git("rev-parse", "r2-engine-v1.1^{commit}").strip()
    return {"engine_version": ENGINE_VERSION, "engine_tag": "r2-engine-v1.1", "engine_tag_commit": tag, "head": git("rev-parse", "HEAD").strip(),
            "includes": ["src/eoo_engine", "src/eoo_engine_git (Git-backed store, Engine-participating by import closure)", "src/eoo_ir (loaded by the Engine)",
                         "domains/manufacturing", "domains/project (ir.v2.json, the default contract)"]}


def engine_clean() -> dict:
    out = git("status", "--porcelain", "--", *PROTECTED)
    return {"paths_dirty": [ln[3:] for ln in out.splitlines()], "clean": not out.strip()}


def oracle_facts() -> list:
    import ast
    out = []
    for p in sorted((ROOT / "oracles/h20").glob("*.py")):
        imps = sorted({(n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
                       for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, (ast.Import, ast.ImportFrom))
                       for a in (n.names if isinstance(n, ast.Import) else [None])})
        out.append({"file": p.relative_to(ROOT).as_posix(), "sha256": sha_file(p), "imports": imps,
                    "forbidden_imports": [i for i in imps if i in FORBIDDEN_IMPORTS]})
    return out


def classify_participants(t: Tracer, scanned: set) -> dict:
    rows = {"scanned_engine_closure": set(), "binding_side": set(), "harness_side": set(), "unscanned_participants": set(), "third_party_or_stdlib": 0}
    domain_side = set(closure(roots=domain_roots())["files"])  # what the domain packs import: domain logic dependencies, not Engine
    for f in t.dispatch_files:
        if f.startswith("<"):  # interpreter pseudo-files (<frozen os>, <string>, generated methods)
            rows["third_party_or_stdlib"] += 1
            continue
        p = Path(f).resolve()
        try:
            rel = p.relative_to(ROOT).as_posix()
        except ValueError:
            rows["third_party_or_stdlib"] += 1
            continue
        if ".venv/" in rel:
            rows["third_party_or_stdlib"] += 1
        elif rel in scanned:
            rows["scanned_engine_closure"].add(rel)
        elif rel.startswith(BINDING_SIDE) or rel in domain_side:
            rows["binding_side"].add(rel)
        elif rel.startswith(HARNESS_SIDE):
            rows["harness_side"].add(rel)
        else:
            rows["unscanned_participants"].add(rel)
    return {k: (sorted(v) if isinstance(v, set) else v) for k, v in rows.items()}


def static_payload(t: Tracer) -> dict:
    a = static_audit.audit()
    part = classify_participants(t, set(a["closure"]["files"]))
    never = sorted(set(a["closure"]["files"]) - set(part["scanned_engine_closure"]))
    return {**a, "candidate": candidate(), "engine_files_sha256": engine_hashes(), "engine_files": engine_clean(), "oracle": oracle_facts(),
            "participation": {**part, "scanned_files_not_seen_executing": never,
                              "method": "sys.setprofile during every workload; a file counts when one of its functions was called while the "
                                        "Engine was inside a dispatch operation. Binding-side = domains/** (logic + adapters, audited as adapters); "
                                        "harness-side = bindings/adapters supplied by the experiment itself."}}


def adapter_payload(t: Tracer) -> dict:
    st = adapter_static.audit()
    neg = adapter_dynamic.taint_known_negative(Tracer)
    pw = provenance_writes.probes(Tracer)
    main = t.provenance_numbers()  # every adapter call of the workloads: the text written == effect['envelope_text']
    parts = [main, *pw["known_positive"].values()]
    prov = {"workloads": main, "probes": pw, "adapter_provenance_writes": sum(x["adapter_provenance_writes"] for x in parts),
            "adapter_provenance_verbatim_mismatches": sum(x["adapter_provenance_verbatim_mismatches"] for x in parts),
            "first_mismatches": [m for x in parts for m in x["first_mismatches"]][:5],
            "known_negative_detected": pw["known_negative_detected"]}
    return {"static": st, "dynamic": {"provenance_verbatim": prov,
        "adapter_calls_observed": {f"{c}.{m}": n for (c, m), n in sorted(t.adapter_calls.items())},
        "governance_calls_inside_adapters": t.adapter_violations, "taint_known_negative": neg,
        "engine_owns_idempotency_probe": adapter_dynamic.idempotency_probe(), "ok_mode_probe": adapter_dynamic.ok_mode_probe(),
        "guarded_engine_functions": [f"{a}.{b}" for a, _m, b in __import__("eoo_h20.trace", fromlist=["x"]).GUARDED_MODULE_FNS]
                                    + ["Engine." + x for x in __import__("eoo_h20.trace", fromlist=["x"]).GUARDED_ENGINE]
                                    + ["Journal.append", "AppendOnlyLog.append"]},
        "judgement_calls": [
            "Engine v1.2: the Engine composes the provenance envelope; GitAdapter / GitStore write effect['envelope_text'] verbatim as the "
            "commit message and return the Git facts (commit, base, head at write, merge, state digest, writer) as the response. "
            "static.declared_exceptions is EMPTY; the static rule provenance_composition flags any adapter that renders provenance itself.",
            "WmsFake / GitFake / GitAdapter answer a repeated call for the same execution / effect id with the stored response (external-system dedupe, as real "
            "WMS / Git would). The Engine's own idempotency decision is shown independent of it by dynamic.engine_owns_idempotency_probe.",
            "GitStore re-validates rows with the Engine's own would_be() (integrity of the external system, reusing Engine code, no re-implementation).",
            "The static audit is a vocabulary audit: a check under an innocuous name is invisible to it (mutant A1b); the in-adapter taint and the ok-mode "
            "probe are the behavioural complements."]}


def synthetic_payload(seed: int, target: int) -> dict:
    h0, f0, t = engine_hashes(), dispatch_fingerprint(), Tracer()
    rows, defs, executed, i = {}, [], 0, 0
    with t.installed():
        while len(rows) < target and i < 40:
            for d in synth.generate(seed * 1000 + i, 700):
                executed += 1
                sha = synth_run.definition_sha(d)
                if sha not in rows:
                    rows[sha] = synth_run.run(d)
                    defs.append(d)
            i += 1
    al = alias.probe(defs[:400])
    h1, f1 = engine_hashes(), dispatch_fingerprint()
    tokens = static_audit.A.collect_tokens()
    clash = sorted({v for d in defs for v in synth.ids(d).values() if v in tokens})
    R = list(rows.values())
    kinds = sorted({k for r in R for k in r["kinds"]})
    return {"candidate": candidate(), "generated_examples": executed, "unique_definitions": len(rows),
            "unique_structures": len({r["structure_sha"] for r in R}), "mismatching_definitions": sum(1 for r in R if r["mismatches"]),
            "engine_files_sha256_before": h0, "engine_files_sha256_after": h1, "engine_edited": h0 != h1,
            "dispatch_fingerprint_before": f0, "dispatch_fingerprint_after": f1, "dispatch_table_changed": f0 != f1,
            "kinds_used": kinds, "kinds_not_in_dispatch_table": sorted(set(kinds) - set(DISPATCH_TABLE)),
            "synthetic_ids_equal_to_domain_tokens": clash,
            "dispatch_ops_used": sorted({f"{k}.{o}" for (_p, k, o) in t.dispatch}), "alias_invariance": al,
            "by_effect": dict(Counter(r["effect"] for r in R)), "by_policy": dict(Counter(r["policy"] for r in R)),
            "by_observed_state": dict(Counter(r["observed_state"] for r in R)),
            "history_paths": dict(Counter(" > ".join(r["history"]) for r in R)),
            "retries_checked": sum(1 for r in R if r["retry_ok"]), "replays_identical": sum(1 for r in R if r["replay_ok"]),
            "functions_checked": len(R), "definitions": R}


def traces_payload(seed: int, n_machine: int, suite_args: list | None = None) -> tuple[dict, Tracer]:
    t = Tracer()
    with t.installed(), profiling_dispatch(t):
        suites = {"pytest": workloads.run_pytest(suite_args), "state_machine_sample": workloads.machine_sample(seed, n_machine),
                  "generic_sweep": workloads.generic_sweep(range(6)), "read_sweep": workloads.read_sweep()}
    reg = payloads.registered()
    bindings = {d: _bound_callables(d) for d in reg}
    base = loc.baseline(reg, bindings)
    return payloads.dispatch_traces(t, suites, {"baseline_contextual": base}), t


def _bound_callables(dom: str) -> int:
    from domains.manufacturing.pack import build_pack as bm
    from domains.project.pack import build_pack as bp
    pack = bm() if dom == "manufacturing" else bp()
    return len(pack[0].keys())


def build(seed: int, n_synth: int, n_machine: int, n_probe: int, suite_args: list | None = None) -> tuple[dict, dict]:
    traces, t = traces_payload(seed, n_machine, suite_args)
    p = {"engine-static-audit.json": static_payload(t), "dispatch-traces.json": traces,
         "adapter-responsibility-audit.json": adapter_payload(t),
         "synthetic-resource-results.json": synthetic_payload(seed, n_synth),
         "mutation-results.json": mutants.run_all(n_probe)}
    corpus = sha_text(json.dumps(sorted(r["sha"] for r in p["synthetic-resource-results.json"]["definitions"])))
    return p, {"corpus_hash": corpus, "unique": p["synthetic-resource-results.json"]["unique_definitions"]}


def run(seed: int, n_synth: int, out_root: Path, exp_id: str, n_machine: int = 100, n_probe: int = 150, suite_args: list | None = None) -> dict:
    pre = prov.preflight()
    with immutable_dir(out_root, exp_id) as tmp:
        payloads_, info = build(seed, n_synth, n_machine, n_probe, suite_args)
        p = prov.provenance(pre, exp_id, HID, seed, info["corpus_hash"], HARNESS, engine_version=ENGINE_VERSION,
                            candidate=candidate())
        for fn in REQUIRED:
            prov.write(tmp, fn, prov.wrap(p, fn[:-5], payloads_[fn]))
    return info
