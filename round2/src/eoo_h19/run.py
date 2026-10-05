"""Frozen H19 experiment run: builds the five evidence payloads and writes them (refuses to overwrite)."""
from __future__ import annotations

import subprocess
import types
from pathlib import Path

from domains._pack import load_ir
from domains.project.logic.freeze import git_blob_reader
from eoo_engine import ENGINE_VERSION
from eoo_exp import provenance as prov
from eoo_exp.outdir import immutable_dir
from eoo_exp.util import ROOT

from . import audit, gen, independence, mutants, storelevel
from .rebuild import rebuild

HID = "H19"
REQUIRED = ["rebuild-hashes.json", "concurrency-state-machine.json", "canonical-change-audit.json", "historical-binding-results.json", "mutation-results.json"]
HARNESS = [*sorted((ROOT / "src/eoo_h19").glob("*.py")), *sorted((ROOT / "src/eoo_engine_git").glob("*.py")), *sorted((ROOT / "src/eoo_exp").glob("*.py")),
           *sorted((ROOT / "oracles/h19").glob("*.py")), *sorted((ROOT / "src/eoo_h18").glob("*.py")), ROOT / "domains/project/pack.py", ROOT / "domains/_pack.py",
           *sorted((ROOT / "domains/project/logic").glob("*.py")), ROOT / "domains/project/ir.v3.json", ROOT / "scripts/run_h19.py", ROOT / "scripts/evaluate_h19.py"]
H19_CLASSES = gen.CLASSES


def head_sha() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def engine_rebuild(a: dict) -> dict:
    env = types.SimpleNamespace(store=a["rig"].store, package=a["rig"].package, raw=a["raw"])
    rb = rebuild(env, [(s, None, None) for s in a["raw"].all_commits()])
    return {**rb, "fsck": a["raw"].fsck(), "oracle_state_checked": False,
            "note": "Engine-level histories have no oracle DAG prediction (the oracle is domain-blind); they are rebuilt, bijection-checked and projection-checked."}


def run_mutations(scenarios: list, reader, audit_seed: int, audit_n: int, ir_version=None, log=print) -> dict:
    control = storelevel.failures(storelevel.run_corpus(scenarios, batch=200, ir_version=ir_version, log=lambda m: None))
    out, ctl_audit = [], audit.summarize(audit.run_audit(reader, audit_seed, audit_n, ir_version=ir_version, log=lambda m: None)["cases"])
    for m in mutants.REGISTRY:
        if m["level"] == "store":
            with m["ctx"]():
                res = storelevel.run_corpus(scenarios, batch=200, ir_version=ir_version, log=lambda x: None)
            f = storelevel.failures(res)
            out.append({"id": m["id"], "target": m["target"], "level": "store", "expected_check": m["expect"], "failures": f, "control_failures": control,
                        "killed": f[m["expect"]] > 0 and control[m["expect"]] == 0, "failing_checks": sorted(k for k, v in f.items() if v),
                        "exceptions": storelevel.tally(res)["exceptions"], "scenarios": len(scenarios)})
        else:
            a = audit.run_audit(reader, audit_seed, audit_n, ir_version=ir_version, log=lambda x: None, ctx=m["ctx"])
            s = audit.summarize(a["cases"])
            out.append({"id": m["id"], "target": m["target"], "level": "engine", "expected_check": m["expect"], "failures": {"ontology_only_writes": s["ontology_only_writes"]},
                        "control_failures": {"ontology_only_writes": ctl_audit["ontology_only_writes"]}, "killed": s["ontology_only_writes"] > 0 and ctl_audit["ontology_only_writes"] == 0,
                        "failing_checks": ["canonical_change_traced"] if s["ontology_only_writes"] else [], "exceptions": s["exceptions"], "scenarios": s["cases"]})
        log(f"[mut] {out[-1]['id']} killed={out[-1]['killed']} {out[-1]['failing_checks']}")
    after = storelevel.failures(storelevel.run_corpus(scenarios, batch=200, ir_version=ir_version, log=lambda m: None))
    return {"scenarios": len(scenarios), "audit_cases": audit_n, "controls": {"clean": not any(control.values()) and not ctl_audit["ontology_only_writes"],
            "clean_after": not any(after.values()), "failures_before": control, "failures_after": after, "audit_ontology_only_writes_before": ctl_audit["ontology_only_writes"]},
            "mutants": out}


def build(seed: int, n: int, audit_n: int, mut_n: int, mut_audit_n: int, log=print, ir_version=None) -> tuple[dict, dict]:
    sha = head_sha()
    reader = git_blob_reader(sha)
    scenarios, ginfo = gen.generate(seed, n)
    log(f"[run] corpus {ginfo}")
    res = storelevel.run_corpus(scenarios, ir_version=ir_version, log=log)
    t = storelevel.tally(res)
    log(f"[run] store-level done: {t}")
    a = audit.run_audit(reader, seed + 1, audit_n, ir_version=ir_version, log=log)
    asum, ebr = audit.summarize(a["cases"]), engine_rebuild(a)
    from eoo_h18.extras import eoo_only_battery
    battery = eoo_only_battery(a["rig"])
    log(f"[run] audit done: {asum}")
    mut_sc, _ = gen.generate(seed + 2, mut_n)
    mut = run_mutations(mut_sc, reader, seed + 3, mut_audit_n, ir_version, log)
    oi = independence.oracle_imports()
    base = {"engine_version": ENGINE_VERSION, "ir_version": load_ir("project", ir_version)["version"]}
    rb = {**base, "definition": "rebuild = a fresh GitStore (empty caches, a different clock per pass, forward/reverse/shuffled order) asked for canonical_hash and state_at(...).state_hash() of every commit; "
          "equal = identical in every pass, equal to the digest reported at write time, and (store histories) the raw-Git logical state equals the oracle DAG state",
          "store_histories": {"histories": len(res["scenarios"]), "fsck_all_ok": all(res["fsck"]), "repositories": len(res["fsck"]), **{k: v for k, v in res["rebuild"].items() if k != "bad_commits"}},
          "engine_histories": {"histories": asum["cases"], **{k: v for k, v in ebr.items() if k != "bad_commits"}}}
    csm = {**base, "oracle": {"files": [f.name for f in independence.ORACLE_FILES], "import_audit": oi, "model": "oracles/h19/model.py: immutable commit DAG + deterministic projection hash + three-way merge",
                              "input": "logical state read from raw Git with the git CLI (eoo_h19/rawgit.py), never from the Engine or the GitStore"},
           "corpus": ginfo, "required_classes": list(H19_CLASSES), "tally": t, "class_counts": {c: t["classes"].get(c, 0) for c in H19_CLASSES},
           "definitions": {"lost_update": "an accepted write whose CHANGE vs its own base is missing from the new head, or a value it did not change that the previous head had (raw Git)",
                           "silent": "accepted without a conflict record", "generation": "Hypothesis st.randoms(use_true_random=False) with fixed seeds; uniqueness by canonical scenario hash"},
           "scenarios": res["scenarios"]}
    cca = {**base, "summary": asum, "corpus": a["corpus"], "direct_write_battery": battery, "cases": a["cases"],
           "definition": "canonical ontology-only write = any Engine step where: the Engine's store changed, a non-git effect ran, the branch moved without an accepted Action, an accepted Action did not make exactly one "
                         "commit (parent = old head, message naming the execution), or the Engine projected from the new head differs from the logical state read raw from that commit"}
    hb = {**base, "store_level": {k: t[k] for k in ("binds", "binds_pinned", "binds_with_later_change", "rebind_attempts", "rebind_accepted")},
          "engine_level": {k: asum[k] for k in ("bindings", "bindings_hash_same", "bindings_entries_same", "bound_entries")},
          "definition": "a binding is pinned when, after later commits, the original commit still rebuilds to the same digest, the oracle state at that commit is unchanged, and the bound Evidence/Verdict entries "
                        "are unchanged at the head; a rebinding attempt (rewrite of an immutable pin) must be rejected"}
    return ({"rebuild-hashes.json": rb, "concurrency-state-machine.json": csm, "canonical-change-audit.json": cca, "historical-binding-results.json": hb,
             "mutation-results.json": {**base, **mut}}, ginfo)


def run(seed: int, n: int, out_root: Path, exp_id: str, audit_n: int = 600, mut_n: int = 400, mut_audit_n: int = 40, log=print, ir_version=None) -> dict:
    pre = prov.preflight()
    with immutable_dir(out_root, exp_id) as tmp:
        payloads, info = build(seed, n, audit_n, mut_n, mut_audit_n, log, ir_version)
        p = prov.provenance(pre, exp_id, HID, seed, info["corpus_hash"], HARNESS, engine_version=ENGINE_VERSION, real_repo_pinned_commit=head_sha(),
                            ir_version=load_ir("project", ir_version)["version"])
        for fn in REQUIRED:
            prov.write(tmp, fn, prov.wrap(p, fn[:-5], payloads[fn]))
    return info
