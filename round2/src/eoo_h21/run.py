"""Frozen-protocol H21 run: builds the six evidence payloads and writes them (refuses to overwrite)."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from domains._pack import boot, load_ir
from domains.manufacturing.pack import build_pack as mfg_pack
from domains.project.pack import build_pack as prj_pack
from eoo_engine import ENGINE_VERSION
from eoo_exp import provenance as prov
from eoo_exp.outdir import immutable_dir
from eoo_exp.util import ROOT, git, sha_text
from eoo_toolchain import build, load_generated

from . import (adversarial, baseline, cases, conformance, differential, engine_check, handwritten, mutants, polymorphism, static)

HID = "H21"
REQUIRED = ["generated-surface-manifest.json", "handwritten-diff.json", "security-differential.json", "agent-adversarial.json",
            "interface-polymorphism.json", "mutation-results.json"]
HARNESS = [*sorted((ROOT / "src/eoo_h21").glob("*.py")), *sorted((ROOT / "src/eoo_toolchain").glob("*.py")), *sorted((ROOT / "src/eoo_exp").glob("*.py")),
           *sorted((ROOT / "oracles/h21").glob("*.py")), ROOT / "scripts/run_h21.py", ROOT / "scripts/evaluate_h21.py"]
DOMAINS = {"manufacturing": mfg_pack, "project": prj_pack}
MFG_NOW = "2026-01-01T00:00:02+00:00"  # 2 s after the seed's EvidenceSnapshot: FRESH (same constant the domain e2e tests use)
POSITIVE = {"manufacturing": ("planner-1", [("act_transfer_inventory", dict(source_warehouse="WH-C", destination_warehouse="WH-B", part="PX-900", quantity=60))]),
            "project": ("researcher-1", [("act_create_hypothesis", dict(claim="adversarial positive control"))])}


def candidate() -> dict:
    tag = git("rev-parse", "r2-engine-v1.1^{commit}").strip()
    return {"engine_version": ENGINE_VERSION, "engine_tag": "r2-engine-v1.1", "engine_tag_commit": tag, "head": git("rev-parse", "HEAD").strip(),
            "includes": ["src/eoo_engine", "src/eoo_engine_git", "domains/manufacturing", "domains/project (ir.v2.json, the default contract)"]}


def _built(domain: str):
    ir = load_ir(domain)
    d = tempfile.mkdtemp(prefix=f"h21-{domain}-")
    inv = build(ir, d)
    sdk, caps, surf = load_generated(d, inv["package"])
    return ir, d, inv, sdk, caps, surf


def manifest_payload(built: dict) -> dict:
    out = {"candidate": candidate(), "domains": {}}
    for dom, (ir, d, inv, sdk, _c, surf) in built.items():
        d2 = tempfile.mkdtemp(prefix=f"h21-rebuild-{dom}-")
        inv2 = build(ir, d2)
        conf = conformance.check(ir, sdk)
        kinds = {k: sum(1 for t in inv["tools"].values() if t["kind"] == k) for k in ("query", "function", "action")}
        out["domains"][dom] = {"package_id": inv["package_id"], "package_version": inv["package_version"], "ir_sha256": inv["ir_sha256"],
                               "files": inv["files"], "clean_build": True, "rebuild_identical": inv["files"] == inv2["files"],
                               "tools": {"count": len(inv["tools"]), "by_kind": kinds, "names": sorted(inv["tools"])},
                               "ir_counts": {k: len(ir[k]) for k in ("object_types", "link_types", "interfaces", "functions", "actions", "authority_rules")},
                               "conformance": conf, "handwritten_files_in_generated_dir": sorted(
                                   p.name for p in (Path(d) / inv["package"]).glob("*.py") if p.name not in inv["files"])}
    out["toolchain"] = static.toolchain_facts()
    out["domain_token_scan"] = static.domain_token_scan([b[0] for b in built.values()])
    out["oracle"] = static.oracle_facts()
    return out


def security_payload(built: dict, n: int, n_engine: int, seed: int) -> tuple:
    out = {"candidate": candidate(), "domains": {}, "oracle": static.oracle_facts(), "toolchain_imports_oracle": static.toolchain_facts()["imports_oracle"],
           "minimum_runs": n}
    shas = []
    for dom, (ir, _d, _inv, _sdk, _c, surf) in built.items():
        cs = cases.unique_cases(ir, n, seed)
        diff = differential.run(ir, surf, cs)
        eng = boot(dom, DOMAINS[dom]())
        ec = engine_check.run(eng, ir, surf, n_engine, seed + 5)
        uniq = {cases.case_sha(c) for c in cs}
        shas += sorted(uniq)
        glue = ("_held", "mfg_allowed") if dom == "manufacturing" else ("PROJECT_ACTION_ROLE", "project_allowed")
        out["domains"][dom] = {"generated_cases": len(cs), "unique_cases": len(uniq), "case_sha256": sorted(uniq), "differential": diff, "engine_cross_check": ec,
                               "baseline_contextual": baseline.report(dom, ir, glue, cs[:1000]),
                               "dimensions": list(differential.DIMS),
                               "case_space": "roles, relations on object keys, delegation chains (depth<=3), object sets (0-2 objects/type), "
                                             "selector-fault worlds, preregistered thresholds, unregistered principals"}
    return out, sha_text(json.dumps(sorted(shas)))


def adversarial_payload(built: dict, seed: int, n_fuzz: int) -> dict:
    out = {"candidate": candidate(), "domains": {}}
    for dom, (ir, _d, _inv, _sdk, _c, surf) in built.items():
        pack = DOMAINS[dom]()
        eng = boot(dom, pack, clock=(lambda: MFG_NOW) if dom == "manufacturing" else None)  # the mfg freshness policy reads the clock
        pid, tries = POSITIVE[dom]
        out["domains"][dom] = adversarial.run(dom, ir, surf, eng, pack[1], seed, n_fuzz, tries, pid)
    return out


def polymorphism_payload(built: dict, handwritten_diff: dict) -> dict:
    out = {"candidate": candidate(), "domains": {}, "min_implementers": json.loads((ROOT / "protocol/thresholds.json").read_text())["H21"]["min_interface_implementations"]}
    for dom, (ir, _d, _inv, _sdk, _c, surf) in built.items():
        eng = boot(dom, DOMAINS[dom]())
        rows = polymorphism.against_engine(ir, surf, eng)
        for r in rows:
            r["after_adding_two_implementers"] = polymorphism.after_adding_types(ir, r["interface"], r["tool_source"])
        out["domains"][dom] = rows
    out["extended_project_ir_replication_as_seventh_implementer"] = next(s for s in handwritten_diff["end_to_end"]["steps"] if "interface" in s["step"])
    return out


def build_all(seed: int, n_cases: int, n_engine: int, n_mut: int, n_fuzz: int) -> tuple:
    built = {dom: _built(dom) for dom in DOMAINS}
    hw = handwritten.payload(seed, min(n_cases, 3000))
    sec, corpus = security_payload(built, n_cases, n_engine, seed)
    doms = {d: {"ir": b[0], "engine": boot(d, DOMAINS[d]())} for d, b in built.items()}
    p = {"generated-surface-manifest.json": manifest_payload(built), "handwritten-diff.json": hw, "security-differential.json": sec,
         "agent-adversarial.json": adversarial_payload(built, seed, n_fuzz), "interface-polymorphism.json": polymorphism_payload(built, hw),
         "mutation-results.json": {**mutants.run_all(doms, n_mut, seed), "candidate": candidate()}}
    return p, corpus


def run(seed: int, n_cases: int, out_root: Path, exp_id: str, n_engine: int = 1500, n_mut: int = 1000, n_fuzz: int = 150) -> dict:
    pre = prov.preflight()
    with immutable_dir(out_root, exp_id) as tmp:
        payloads, corpus = build_all(seed, n_cases, n_engine, n_mut, n_fuzz)
        p = prov.provenance(pre, exp_id, HID, seed, corpus, HARNESS, engine_version=ENGINE_VERSION, candidate=candidate())
        for fn in REQUIRED:
            prov.write(tmp, fn, prov.wrap(p, fn[:-5], payloads[fn]))
    return {"corpus_hash": corpus, "unique_cases": {d: v["unique_cases"] for d, v in payloads["security-differential.json"]["domains"].items()}}
