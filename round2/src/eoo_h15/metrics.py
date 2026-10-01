"""compiler-diff-metrics: size / complexity / time of the two surfaces, side by side (a view; no verdict logic)."""
from __future__ import annotations

import statistics
import time

import openpona

import eoo_dsl
import eoo_dsl.compiler as dsl_compiler
import eoo_dsl.spec as dsl_spec
import eoo_openpona
import eoo_openpona.compiler as op_compiler
import eoo_openpona.lines as op_lines
from eoo_openpona import gaps as op_gaps
from eoo_openpona.templates import T, TYPE_GLOSS
from eoo_openpona.vocab import RESOURCE_HEADS

from .slots import line_rules
from .util import KINDS, ROOT, loc, resource_counts, tokens_re, tokens_ws

DOMAINS = ("manufacturing", "project")


def _loc(pkg: str) -> dict:
    files = sorted((ROOT / "src" / pkg).glob("*.py"))
    return {"files": {f.name: loc(f) for f in files}, "total": sum(loc(f) for f in files)}


def _dsl_fields() -> dict:
    seen, n = set(), 0

    def walk(s):
        nonlocal n
        if isinstance(s, dsl_spec.Obj):
            if id(s) in seen:
                return
            seen.add(id(s))
            n += len(s.required) + len(s.optional)
            for v in list(s.required.values()) + list(s.optional.values()):
                walk(v)
        elif isinstance(s, dsl_spec.List):
            walk(s.item)
    walk(dsl_spec.PACKAGE)
    return {"object_fields": n, "type_constructor_keys": 3, "cardinality_keys": 2, "table_size": n + 5,
            "note": "distinct (object, field) entries of eoo_dsl.spec.PACKAGE + 3 type-constructor keys + min/max"}


def _op_lines_by_kind(text: str) -> dict:
    cur, out = "package", {}
    for ln in line_rules(text):
        if ln.tid.startswith(("pkg.", "meta.")):
            k = "package"
        elif ln.tid == "res.decl":
            head = ln.slots[0][1].split()[0]
            cur = k = RESOURCE_HEADS[head]
        else:
            k = cur
        out[k] = out.get(k, 0) + 1
    return out


def _dsl_lines_by_kind(yaml: str) -> dict:
    out, cur = {}, "package"
    for ln in yaml.splitlines():
        if ln and not ln[0].isspace() and ln.endswith(":") or (ln and not ln[0].isspace() and ":" in ln and ln.split(":")[0] in KINDS):
            key = ln.split(":")[0]
            cur = key if key in KINDS else "package"
        out[cur] = out.get(cur, 0) + 1
    return out


def _time(fn, n: int = 3) -> float:
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    return statistics.median(ts)


def domain_metrics(name: str, ir: dict) -> dict:
    text, rec = eoo_openpona.render(ir)
    rec_text = eoo_openpona.dump_record(rec)
    yaml = eoo_dsl.render(ir)
    n = sum(resource_counts(ir).values())
    op_bytes = len(text.encode()) + len(rec_text.encode())
    return {
        "domain": name, "resources": n, "resources_by_kind": resource_counts(ir),
        "openpona": {"text_bytes": len(text.encode()), "record_bytes": len(rec_text.encode()), "bytes": op_bytes,
                     "text_lines": len(text.splitlines()), "record_lines": len(rec_text.splitlines()),
                     "lines": len(text.splitlines()) + len(rec_text.splitlines()),
                     "tokens_ws": tokens_ws(text) + len(rec) * 2, "tokens_re": tokens_re(text) + tokens_re(rec_text),
                     "text_tokens_ws": tokens_ws(text), "record_atoms": len(rec),
                     "bytes_per_resource": op_bytes / n, "text_lines_per_resource": len(text.splitlines()) / n,
                     "lines_per_resource": (len(text.splitlines()) + len(rec_text.splitlines())) / n,
                     "text_lines_by_resource_kind": _op_lines_by_kind(text),
                     "render_s": _time(lambda: eoo_openpona.render(ir)),
                     "compile_s_cold_parser_cache": _time(lambda: (op_lines.parsed.cache_clear(), op_compiler.compile(text, rec)), 2)},
        "dsl": {"bytes": len(yaml.encode()), "lines": len(yaml.splitlines()), "tokens_ws": tokens_ws(yaml),
                "tokens_re": tokens_re(yaml), "bytes_per_resource": len(yaml.encode()) / n,
                "lines_per_resource": len(yaml.splitlines()) / n, "lines_by_resource_kind": _dsl_lines_by_kind(yaml),
                "render_s": _time(lambda: eoo_dsl.render(ir)), "compile_s": _time(lambda: dsl_compiler.compile(yaml))},
        "ratio_openpona_over_dsl": {"bytes": op_bytes / len(yaml.encode()), "text_bytes_only": len(text.encode()) / len(yaml.encode()),
                                    "lines": (len(text.splitlines()) + len(rec_text.splitlines())) / len(yaml.splitlines()),
                                    "tokens_re": (tokens_re(text) + tokens_re(rec_text)) / tokens_re(yaml)},
    }


def build(domain_irs: dict, gen_stats: dict, ambiguity_summary: dict, tokens_seen: set[str]) -> dict:
    gl = op_gaps.gaps()
    inventory = set(openpona.TOKENS)
    outside = sorted(tokens_seen - inventory)
    new_prim = [g for g in gl if g.get("would_need") in ("new_token", "grammar_change")]
    sidecar = [g for g in gl if g.get("would_need") == "structural_sidecar"]
    return {
        "compiler_loc": {"openpona": {**_loc("eoo_openpona"), "pinned_parser_not_counted": "openpona package (parser.py, grammar.lark)"},
                         "dsl": _loc("eoo_dsl"),
                         "shared_not_counted": "eoo_ir (oracle, validate, Index) is used by both compilers' referential checks"},
        "encoding_rules": {"openpona_line_templates": len(T), "openpona_type_phrases": len(TYPE_GLOSS),
                           "dsl_field_table": _dsl_fields()},
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
