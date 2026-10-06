"""compiler-diff-metrics for the H15 v2 candidate (same fields as metrics.build, v2 surface; a view, no verdict logic)."""
from __future__ import annotations

import openpona

import eoo_dsl
import eoo_dsl.compiler as dsl_compiler
import eoo_openpona2
import eoo_openpona2.compiler as op2_compiler
import eoo_openpona2.lines as op2_lines
from eoo_openpona2 import gaps as op2_gaps
from eoo_openpona2.lines import read_line
from eoo_openpona2.phrases import T, TYPE_GLOSS
from eoo_openpona2.table import table_size
from eoo_openpona2.vocab import RESOURCE_HEADS

from .metrics import DOMAINS, _dsl_fields, _dsl_lines_by_kind, _loc, _time
from .util import resource_counts, tokens_re, tokens_ws


def _op_lines_by_kind(text: str) -> dict:
    cur, out = "package", {}
    for i, ln in enumerate(text.splitlines(), 1):
        line = read_line(i, ln)
        if line.rid.startswith(("pkg.", "meta.")):
            k = "package"
        elif line.rid == "res.decl":
            cur = k = RESOURCE_HEADS[line.text.split()[0]]
        else:
            k = cur
        out[k] = out.get(k, 0) + 1
    return out


def domain_metrics(name: str, ir: dict) -> dict:
    text, rec = eoo_openpona2.render(ir)
    rec_text = eoo_openpona2.dump_record(rec)
    yaml = eoo_dsl.render(ir)
    n = sum(resource_counts(ir).values())
    op_bytes = len(text.encode()) + len(rec_text.encode())
    lines = text.splitlines()
    return {
        "domain": name, "resources": n, "resources_by_kind": resource_counts(ir),
        "openpona": {"text_bytes": len(text.encode()), "record_bytes": len(rec_text.encode()), "bytes": op_bytes,
                     "text_lines": len(lines), "record_lines": len(rec_text.splitlines()),
                     "lines": len(lines) + len(rec_text.splitlines()),
                     "tokens_ws": tokens_ws(text) + len(rec) * 2, "tokens_re": tokens_re(text) + tokens_re(rec_text),
                     "text_tokens_ws": tokens_ws(text), "record_atoms": len(rec),
                     "distinct_lines": len(set(lines)),
                     "bytes_per_resource": op_bytes / n, "text_lines_per_resource": len(lines) / n,
                     "lines_per_resource": (len(lines) + len(rec_text.splitlines())) / n,
                     "text_lines_by_resource_kind": _op_lines_by_kind(text),
                     "render_s": _time(lambda: eoo_openpona2.render(ir)),
                     "compile_s_cold_parser_cache": _time(lambda: (op2_lines.parsed.cache_clear(), op2_compiler.compile(text, rec)), 2)},
        "dsl": {"bytes": len(yaml.encode()), "lines": len(yaml.splitlines()), "tokens_ws": tokens_ws(yaml),
                "tokens_re": tokens_re(yaml), "bytes_per_resource": len(yaml.encode()) / n,
                "lines_per_resource": len(yaml.splitlines()) / n, "lines_by_resource_kind": _dsl_lines_by_kind(yaml),
                "render_s": _time(lambda: eoo_dsl.render(ir)), "compile_s": _time(lambda: dsl_compiler.compile(yaml))},
        "ratio_openpona_over_dsl": {"bytes": op_bytes / len(yaml.encode()), "text_bytes_only": len(text.encode()) / len(yaml.encode()),
                                    "lines": (len(lines) + len(rec_text.splitlines())) / len(yaml.splitlines()),
                                    "tokens_re": (tokens_re(text) + tokens_re(rec_text)) / tokens_re(yaml)},
    }


def build(domain_irs: dict, gen_stats: dict, ambiguity_summary: dict, tokens_seen: set[str]) -> dict:
    gl = op2_gaps.gaps()
    inventory = set(openpona.TOKENS)
    outside = sorted(tokens_seen - inventory)
    new_prim = [g for g in gl if g.get("would_need") in ("new_token", "grammar_change")]
    sidecar = [g for g in gl if g.get("would_need") == "structural_sidecar"]
    return {
        "candidate_surface": "openpona2",
        "compiler_loc": {"openpona": {**_loc("eoo_openpona2"), "pinned_parser_not_counted": "openpona package (parser.py, grammar.lark)"},
                         "dsl": _loc("eoo_dsl"),
                         "shared_not_counted": "eoo_ir (oracle, validate, Index) is used by both compilers' referential checks"},
        "encoding_rules": {"openpona_line_templates": len(T), "openpona_type_phrases": len(TYPE_GLOSS),
                           "openpona_phrase_table_concrete_lines": table_size(), "dsl_field_table": _dsl_fields()},
        "domains": [domain_metrics(d, domain_irs[d]) for d in DOMAINS],
        "gap_constructs": {"count": len(gl), "entries": gl, "need_new_token_or_grammar_change": len(new_prim),
                           "need_structural_sidecar": len(sidecar)},
        "primitive_tokens": {"pinned_inventory_size": len(inventory), "tokens_seen_in_all_rendered_text": len(tokens_seen),
                             "tokens_outside_pinned_inventory": outside, "new_primitive_tokens_required": len(new_prim) + len(outside),
                             "adaptation_events": 0},
        "ambiguity_rejection_rate": {s: {"declared_fail_closed": f"{v['declared_fail_closed']}/{v['declared_total']}",
                                         "deletion_mutants_total": v["deletion_total"],
                                         "deletion_mutants_raised": v["deletion_raised"],
                                         "deletion_mutants_accepted_exact": v["deletion_accepted_exact"],
                                         "deletion_violations": v["deletion_violations"],
                                         "raised_rate": v["deletion_raised"] / max(1, v["deletion_total"])}
                                     for s, v in ambiguity_summary.items()},
        "generated_sample": gen_stats,
    }
