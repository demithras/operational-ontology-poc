"""Assemble the six evidence files of the frozen H15 run."""
from __future__ import annotations

import sys

from . import ambiguity, candidate, domains, evidence, metrics, metrics2, mutants, sidecar, sidecar2
from .genloop import GenLoop
from .corpus import generate
from .util import ROOT, load_json, resource_counts
from . import slots

import eoo_openpona

SIDECAR_N = 2000
DELETION_LINE_TARGET = 3000  # OpenPona line-deletion mutants drawn from generated packages (contract: >= 1,000)
MUTATION_PKGS = 60
MIN_LINES = 30


def substantive(pkgs: list[dict], k: int | None = None, line_target: int | None = None) -> list[tuple[str, dict]]:
    """Deterministic selection of non-trivial packages (>= MIN_LINES OpenPona lines) in corpus order, labelled by
    their position in the kept sample; stops after k packages or once line_target lines are reached."""
    out, lines = [], 0
    for i, p in enumerate(pkgs):
        n = len(_render(p)[0].splitlines())
        if n < MIN_LINES:
            continue
        out.append((f"kept[{i}]", p))
        lines += n
        if (k and len(out) >= k) or (line_target and lines >= line_target):
            break
    return out


def _render(ir: dict):
    return candidate.current().pkg.render(ir) if candidate.is_v2() else eoo_openpona.render(ir)


def _sidecar(domain_irs: dict, head: list[dict]) -> dict:
    def one(label, ir):
        text, rec = eoo_openpona.render(ir)
        a = sidecar.audit_package(ir, text, rec)
        a["vocabulary"] = slots.record_vocabulary(text, rec)
        a["label"] = label
        return a

    res = {"domains": {}, "generated_sample": {}}
    findings, vocab_bad = [], 0
    for d, ir in domain_irs.items():
        a = one(d, ir)
        findings += [{**f, "where": d} for f in a["alpha"]["findings"] + a["shape"]["findings"]]
        vocab_bad += not a["vocabulary"]["ok"]
        res["domains"][d] = {"alpha_rename_ok": a["alpha"]["ok"], "line_only_shape_ok": a["shape"]["ok"],
                             "record_vocabulary": a["vocabulary"], "reference_slots_total": a["ref_slots_total"],
                             "reference_slots_via_coreference_labels": a["ref_slots_via_labels"],
                             "reference_slots_by_role": a["roles"], "alpha_error": a["alpha"].get("error"),
                             "shape_error": a["shape"].get("error")}
    g = {"packages": 0, "alpha_failed": 0, "shape_failed": 0, "vocabulary_failed": 0, "reference_slots_total": 0,
         "reference_slots_via_coreference_labels": 0, "record_slots_by_class": {}, "failing": []}
    for i, ir in enumerate(head[:SIDECAR_N]):
        a = one(f"generated[{i}]", ir)
        g["packages"] += 1
        g["alpha_failed"] += not a["alpha"]["ok"]
        g["shape_failed"] += not a["shape"]["ok"]
        g["vocabulary_failed"] += not a["vocabulary"]["ok"]
        g["reference_slots_total"] += a["ref_slots_total"]
        g["reference_slots_via_coreference_labels"] += a["ref_slots_via_labels"]
        for k, v in a["vocabulary"]["slots_by_class"].items():
            g["record_slots_by_class"][k] = g["record_slots_by_class"].get(k, 0) + v
        if not (a["alpha"]["ok"] and a["shape"]["ok"] and a["vocabulary"]["ok"]):
            findings += [{**f, "where": a["label"]} for f in a["alpha"]["findings"] + a["shape"]["findings"]]
            if len(g["failing"]) < 10:
                g["failing"].append({"label": a["label"], "package": ir, "alpha": a["alpha"], "shape": a["shape"],
                                     "vocabulary": a["vocabulary"]})
    res["generated_sample"] = g
    ind = [f for f in findings if f["classification"] == "indispensable_semantic_sidecar"]
    res["findings"] = findings[:100]
    res["findings_total"] = len(findings)
    res["indispensable_semantic_sidecar_findings"] = len(ind)
    res["record_vocabulary_violations"] = vocab_bad + g["vocabulary_failed"]
    res["indispensable_sidecar_count"] = len(ind) + res["record_vocabulary_violations"]
    res["procedure"] = ("record schema; alpha-renaming (rho+hex, decode back must equal the IR); line-only shape (unique "
                        "placeholder per slot, substitute back must equal the IR with numbers masked); structural items "
                        "found only in the record are listed in 'findings'")
    return res


def run(seed: int, n: int, out_dir, exp_id: str, log=sys.stderr) -> dict:
    pre = evidence.preflight()
    dom = {d: load_json(f"domains/{d}/ir.json") for d in domains.DOMAINS}
    loop = GenLoop(n, log)
    produced = generate(n, seed, loop)
    print(f"[run] generated {produced}; shrinking counterexamples", file=log, flush=True)
    gen = loop.payload(n, seed, loop.shrink(seed))
    real = domains.run()
    print("[run] ambiguity", file=log, flush=True)
    dels = substantive(loop.head, line_target=DELETION_LINE_TARGET)
    amb = ambiguity.run(dels, [(d, dom[d]) for d in dom], seed)
    print("[run] sidecar", file=log, flush=True)
    side = sidecar2.run_audit(dom, loop.head) if candidate.is_v2() else _sidecar(dom, loop.head)
    print("[run] mutation", file=log, flush=True)
    mut = mutants.run([p for _, p in substantive(loop.head, k=MUTATION_PKGS)] or loop.head[:MUTATION_PKGS], seed)
    print("[run] metrics", file=log, flush=True)
    stats = {s: {"mean_render_ms": gen["surfaces"][s]["mean_render_ms"], "mean_compile_ms": gen["surfaces"][s]["mean_compile_ms"],
                 "packages": gen["generation"]["generated"]} for s in gen["surfaces"]}
    met = (metrics2 if candidate.is_v2() else metrics).build(dom, stats, amb["summary"], set(gen["tokens_seen_in_openpona_text"]))
    prov = evidence.provenance(pre, exp_id, seed, gen["generation"]["corpus_sha256"])
    files = {"real-domain-roundtrip.json": real, "generated-roundtrip.json": gen, "ambiguity-corpus.json": amb,
             "sidecar-audit.json": side, "mutation-results.json": mut, "compiler-diff-metrics.json": met}
    for name, payload in files.items():
        evidence.write(out_dir, name, evidence.wrap(prov, name, payload))
    return {k: v for k, v in prov.items() if k in ("git_commit", "harness_dirty")}
