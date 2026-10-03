"""Real-domain round trips: both registered domains, both surfaces, committed artifacts AND fresh renders."""
from __future__ import annotations

import eoo_dsl
import eoo_openpona
import eoo_openpona.compiler as op_compiler
from eoo_ir import equivalent, validate
from eoo_openpona import load_record

from . import candidate
from .roundtrip import attempt, public
from .surfaces import DSL, OPENPONA
from .util import ROOT, canon, load_json, resource_counts

DOMAINS = ("manufacturing", "project")


def _judge(ir: dict, compile_fn) -> dict:
    try:
        out = compile_fn()
    except Exception as e:  # noqa: BLE001 - the failure itself is the result
        return {"compiled": False, "equivalent": False, "error": f"{type(e).__name__}: {str(e)[:300]}", "diffs": [],
                "exact": False, "valid_ir": False, "resource_counts_out": None}
    eq = equivalent(ir, out)
    return {"compiled": True, "equivalent": eq.ok, "diffs": eq.diffs[:10], "exact": canon(out) == canon(ir),
            "valid_ir": validate(out) == [], "resource_counts_out": resource_counts(out)}


def run() -> dict:
    out = {}
    for d in DOMAINS:
        ir = load_json(f"domains/{d}/ir.json")
        cand = candidate.current()
        v2 = candidate.is_v2()
        render, comp, load = ((cand.pkg.render, cand.compiler.compile, cand.pkg.load_record) if v2
                              else (eoo_openpona.render, op_compiler.compile, load_record))
        op_text = (ROOT / f"domains/{d}/{cand.domain_op}").read_text()
        op_rec_text = (ROOT / f"domains/{d}/{cand.domain_rec}").read_text()
        dsl_text = (ROOT / f"domains/{d}/dsl.yaml").read_text()
        fresh_text, fresh_rec = render(ir)
        committed = _judge(ir, lambda: comp(op_text, load(op_rec_text)))
        fresh = _judge(ir, lambda: (candidate_surface() if v2 else OPENPONA).compile((fresh_text, fresh_rec)))
        dsl_committed = _judge(ir, lambda: DSL.compile(dsl_text))
        dsl_fresh = _judge(ir, lambda: DSL.compile(eoo_dsl.render(ir)))
        rc = resource_counts(ir)
        out[d] = {
            "resources_ir": rc, "resources_total": sum(rc.values()),
            "openpona": {"committed": committed, "fresh_render": fresh,
                         "committed_equals_fresh_render": op_text == fresh_text and load(op_rec_text) == fresh_rec,
                         "equivalent": committed["equivalent"] and fresh["equivalent"],
                         "encoded_completely": committed["compiled"] and fresh["compiled"] and
                         committed["resource_counts_out"] == rc and fresh["resource_counts_out"] == rc,
                         "lines": len(op_text.splitlines()), "record_atoms": len(load(op_rec_text))},
            "dsl": {"committed": dsl_committed, "fresh_render": dsl_fresh, "committed_equals_fresh_render": dsl_text == eoo_dsl.render(ir),
                    "equivalent": dsl_committed["equivalent"] and dsl_fresh["equivalent"],
                    "encoded_completely": dsl_committed["compiled"] and dsl_fresh["compiled"] and
                    dsl_committed["resource_counts_out"] == rc and dsl_fresh["resource_counts_out"] == rc},
        }
    return out


def candidate_surface():
    from .surfaces import SURFACES
    return SURFACES["openpona"]
