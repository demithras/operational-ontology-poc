"""REPORT.md: a generated view of verdict.json and the evidence payloads (not an authority)."""
from __future__ import annotations

import json
from pathlib import Path


def _p(d: Path, f: str):
    try:
        return json.loads((d / f).read_text())["payload"]
    except Exception:  # noqa: BLE001
        return None


def _t(rows: list[list], head: list[str]) -> str:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render_report(d: Path, v: dict) -> str:
    n = v["numbers"]
    L = [f"# H15 report: {v['experiment_id']}", "", "Generated from the evidence JSON by `scripts/evaluate_h15.py`; "
         "`verdict.json` and the six evidence files are the authority, this file is a view.", "",
         f"**Verdict: {v['verdict']}**", "", "```", json.dumps(v["common"], indent=1), "```", ""]
    if v["problems"] or any(v["protocol_mismatches"].values()):
        L += ["## Problems", "", "```", json.dumps({"problems": v["problems"], "protocol": v["protocol_mismatches"]}, indent=1), "```", ""]
    for key, title in (("support_if", "support_if"), ("reject_if", "reject_if"), ("inconclusive_if", "inconclusive_if"), ("invalid_if", "invalid_if")):
        L += [f"## {title}", "", _t([[r["id"], r["clause"], r["value"]] for r in v["predicates"][key]], ["id", "clause", "holds"]), ""]
    real, gen, amb = _p(d, "real-domain-roundtrip.json"), _p(d, "generated-roundtrip.json"), _p(d, "ambiguity-corpus.json")
    side, mut, met = _p(d, "sidecar-audit.json"), _p(d, "mutation-results.json"), _p(d, "compiler-diff-metrics.json")
    if real:
        L += ["## Real domains", "", _t([[k, x["resources_total"], x["openpona"]["equivalent"], x["openpona"]["encoded_completely"],
                                          x["dsl"]["equivalent"]] for k, x in real.items()],
                                         ["domain", "resources", "OpenPona equivalent", "OpenPona complete", "DSL equivalent"]), ""]
    if gen:
        L += ["## Generated corpus", "", f"valid cases {gen['valid_cases']} (unique {gen['generation']['unique']}), corpus {gen['generation']['corpus_sha256'][:16]}", "",
              _t([[s, x["ok"], x["failed"], x["unrepresentable"], x["exact_equal"], f"{x['mean_render_ms']:.2f}", f"{x['mean_compile_ms']:.2f}"]
                  for s, x in gen["surfaces"].items()], ["surface", "ok", "failed", "unrepresentable", "exact", "render ms", "compile ms"]), ""]
    if amb:
        L += ["## Ambiguity", "", _t([[s] + [x[k] for k in ("declared_total", "declared_fail_closed", "declared_accepted", "deletion_total",
                                                              "deletion_raised", "deletion_accepted_exact", "deletion_violations")]
                                      for s, x in amb["summary"].items()],
                                     ["surface", "declared", "fail closed", "accepted", "deletion mutants", "raised", "accepted exact", "violations"]), ""]
    if side:
        g = side["generated_sample"]
        L += ["## Sidecar audit", "", f"indispensable sidecar count {side['indispensable_sidecar_count']}; findings {side['findings_total']}; "
              f"generated sample {g['packages']} packages: alpha failures {g['alpha_failed']}, shape failures {g['shape_failed']}, "
              f"reference slots {g['reference_slots_total']} of which via coreference labels {g['reference_slots_via_coreference_labels']}.", "",
              _t([[k, x["alpha_rename_ok"], x["line_only_shape_ok"], x["reference_slots_total"], x["reference_slots_via_coreference_labels"]]
                  for k, x in side["domains"].items()], ["domain", "alpha ok", "shape ok", "reference slots", "via labels"]), ""]
    if mut:
        L += ["## Mutation", "", _t([[m["id"], "target" if m["target"] else "extra", m["killed"], json.dumps(m["hits"])] for m in mut["mutants"]],
                                    ["mutant", "kind", "killed", "hits"]), "",
              f"controls clean: {{{', '.join(f'{s}: {c['clean']}' for s, c in mut['controls'].items())}}}", ""]
    if met:
        L += ["## Metrics", "", f"compiler+renderer LOC: OpenPona {met['compiler_loc']['openpona']['total']}, DSL {met['compiler_loc']['dsl']['total']}; "
              f"rules: {met['encoding_rules']['openpona_line_templates']} line templates vs DSL field table {met['encoding_rules']['dsl_field_table']['table_size']}; "
              f"gap constructs {met['gap_constructs']['count']}; new primitive tokens {met['primitive_tokens']['new_primitive_tokens_required']}.", "",
              _t([[x["domain"], x["resources"], x["openpona"]["bytes"], x["dsl"]["bytes"], x["openpona"]["lines"], x["dsl"]["lines"],
                   x["openpona"]["tokens_re"], x["dsl"]["tokens_re"]] for x in met["domains"]],
                 ["domain", "resources", "OP bytes", "DSL bytes", "OP lines", "DSL lines", "OP tokens", "DSL tokens"]), ""]
    L += ["## Interpretation notes", ""] + [f"- {x}" for x in v["interpretation_notes"]] + [""]
    return "\n".join(L)
